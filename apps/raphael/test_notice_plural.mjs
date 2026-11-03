/* test_notice_plural.mjs — one is said as one, in every notice raphael can post.
 *
 *   node apps/raphael/test_notice_plural.mjs
 *
 * DGO-526: «רפאל: 1 קונטיינרים לא בריאים». A count with a fixed plural is wrong Hebrew, and it is
 * wrong in a NOTICE — the one place nobody re-reads before believing it. The rule is the mail
 * screen's (`apps/mail/mailview/static/app.js`): a count of one is its own sentence, any other is the
 * number as the office writes numbers, with the plural.
 *
 * READS AND RUNS THE REAL CODE, not the source text: it extracts each scan's `jsCode` out of the
 * blueprint, gives it a stubbed `this.helpers.httpRequest` (the machine overview the scan reads, the
 * notify endpoint it posts to), runs it twice — one container and two — and reads the TITLE it would
 * have posted. A test that greps for `one(` would pass on a call that is never reached.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const blueprint = join(here, 'blueprint', 'n8n');

let passed = 0, failed = 0;
function ok(cond, what) {
  if (cond) { passed += 1; return; }
  failed += 1;
  console.error('FAIL  ' + what);
}

const jsCodeOf = (file) => {
  const src = readFileSync(join(blueprint, file), 'utf8');
  const m = src.match(/jsCode: `([\s\S]*?)`,\n    \};/);
  if (!m) throw new Error(`${file}: no jsCode found — the shape of a Code node changed`);
  return m[1];
};

/* Run one scan against a stubbed platform and return what it would have posted. */
async function noticeOf(file, overview) {
  const posted = [];
  const helpers = {
    httpRequest: async (opts) => {
      const url = String(opts && opts.url || '');
      if (url.includes('machine:8080/api/overview')) return overview;
      if (url.includes('data-management:8080/api/inventory')) return overview;
      if (url.includes('notifications')) {
        // A scan both POSTS a notice and — when it finds nothing — READS THE LIST BACK and marks its own
        // unread notice read (DGO-537). Only a POST that carries a notification body is a notice this
        // test counts; the read-back is answered with an empty list, so a healthy office still proves
        // "posts nothing" without the close path being left out of the run.
        if (opts.body && opts.body.title) posted.push(opts);
        return url.includes('?limit=') ? { notifications: [] } : { ok: true };
      }
      throw new Error('the scan asked for something this test does not know: ' + url);
    },
  };
  const self = { helpers };
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const fn = new AsyncFunction(jsCodeOf(file));
  const out = await fn.call(self);
  return { titles: posted.map((p) => p.body && p.body.title), json: out && out[0] && out[0].json };
}

const container = (name, extra = {}) => ({
  name, health: 'unhealthy', status: 'running',
  labels: { 'com.docker.compose.service': 'machine', 'com.docker.compose.project': 'p' }, ...extra,
});
const overview = (containers) => ({ containers: [{ ...container('machine'), health: 'healthy' }, ...containers] });

/* ── machine: running-but-unhealthy containers ─────────────────────────────────────────────── */
{
  const one = await noticeOf('raphaelMachine00001.workflow.ts', overview([container('a')]));
  ok(one.titles.length === 1, `machine: one notice for one unhealthy container (got ${one.titles.length})`);
  ok(one.titles[0] === 'רפאל: קונטיינר אחד לא בריא',
     `machine: ONE is said as one — got «${one.titles[0]}»`);
  const two = await noticeOf('raphaelMachine00001.workflow.ts', overview([container('a'), container('b')]));
  ok(two.titles[0] === 'רפאל: 2 קונטיינרים לא בריאים', `machine: two — got «${two.titles[0]}»`);
  const none = await noticeOf('raphaelMachine00001.workflow.ts', overview([]));
  ok(none.titles.length === 0, 'machine: a healthy office posts nothing');
  ok(none.json.ok === true, 'machine: and its finding says ok');
}

/* ── containers: crashed or crash-looping ──────────────────────────────────────────────────── */
{
  const one = await noticeOf('raphaelContainers00001.workflow.ts',
                             overview([container('a', { status: 'restarting' })]));
  ok(one.titles[0] === 'רפאל: קונטיינר אחד קרס או בלולאת ריסטארט',
     `containers: ONE is said as one — got «${one.titles[0]}»`);
  const two = await noticeOf('raphaelContainers00001.workflow.ts',
                             overview([container('a', { status: 'dead' }), container('b', { status: 'restarting' })]));
  ok(two.titles[0] === 'רפאל: 2 קונטיינרים קרסו או בלולאת ריסטארט', `containers: two — got «${two.titles[0]}»`);
}

/* ── data: volumes at risk. The scan reads `volumes` with a level; one at risk is one. ─────── */
{
  const volume = (name) => ({ volume: name, why: 'no backup' });
  const inv = (vols) => ({ state: 'ready', summary: { at_risk: vols } });
  const one = await noticeOf('raphaelData00001.workflow.ts', inv([volume('v1')]));
  ok(one.titles.length === 1, `data: one notice for one volume at risk (got ${one.titles.length})`);
  ok(one.titles[0] === 'רפאל: נפח נתונים אחד בסיכון', `data: ONE is said as one — got «${one.titles[0]}»`);
  const two = await noticeOf('raphaelData00001.workflow.ts', inv([volume('v1'), volume('v2')]));
  ok(two.titles[0] === 'רפאל: 2 נפחי נתונים בסיכון', `data: two — got «${two.titles[0]}»`);
}

/* ── the rule itself, wherever a notice counts something ───────────────────────────────────── */
for (const file of ['raphaelMachine00001', 'raphaelContainers00001', 'raphaelData00001',
                    'raphaelPulse00001']) {
  const src = readFileSync(join(blueprint, file + '.workflow.ts'), 'utf8');
  ok(/const one = \(n, single, many\)/.test(src), `${file}: carries the one() it says its counts with`);
  const counts = [...src.matchAll(/title: *'[^']*' *\+ *([A-Za-z_][\w.]*)\.length *\+ *' *([א-ת]+)/g)];
  ok(counts.length === 0,
     counts.length ? `${file}: a count is still glued to a fixed plural — ${counts.map((m) => m[2]).join(', ')}`
                   : `${file}: no count is glued to a fixed plural`);
}

console.log(`raphael notices: ${passed} check(s) passed` + (failed ? `, ${failed} FAILED` : ''));
process.exit(failed ? 1 : 0);
