/* ui-selfcheck.mjs — the fleet screen's rules that need neither a browser nor a machine.
 *
 * Why this exists. From 2026-09-29 to 2026-10-07 the «אבטחה» look of a machine never drew anything:
 * it read `r.body` from a helper that answers `{ok, status, d}`, threw on the first property, and
 * left «בודק את המחשב…» on the screen for good. A security screen that silently shows nothing is
 * worse than none, and nothing ran this app's screen against an answer — so nothing said so.
 *
 * So this file EVALUATES THE SHIPPED SOURCE (`static/app.js`) in a Node VM with a small DOM stub and
 * canned service answers in the shape `app.py` really returns, and asserts what the owner would see.
 * It is dev tooling: the image copies `*.py` and `static/` only, and gate G72 runs it.
 *
 *   node apps/computers/tools/ui-selfcheck.mjs      # exits non-zero on the first failed assertion
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'static', 'app.js'), 'utf8');

/* ── a DOM stub just real enough for the module to load and for a render to be read ────────────── */
const els = new Map();
function el(id) {
  if (!els.has(id)) {
    const set = new Set();
    els.set(id, {
      id, value: '', textContent: '', innerHTML: '', dataset: {}, disabled: false, onclick: null,
      classList: { add: (c) => set.add(c), remove: (c) => set.delete(c), contains: (c) => set.has(c),
                   toggle: (c, on) => (on ? set.add(c) : set.delete(c)) },
      get parentNode() { return el(id + '^'); },
      insertAdjacentHTML(_where, html) { this.innerHTML += html; },
      addEventListener() {}, focus() {},
    });
  }
  return els.get(id);
}
const html = (id) => el(id).innerHTML;

/* ── the service, canned ──────────────────────────────────────────────────────────────────────── */
const GB = 1024 ** 3;
const FLEET = { office_key: { public_key: 'ssh-ed25519 AAAA office-key', fingerprint: 'SHA256:abc' }, computers: [
  { id: 'local', builtin: true, label: 'המחשב הזה', note: 'המכונה שמריצה את הלשכה — אינה ניתנת למחיקה',
    host: 'host.internal', user: 'root', port: 22, ok: false, state: 'needs_action', reason: 'מפתח המחשב אינו תואם' },
  { id: 'srv', label: 'שרת פיתוח', host: '203.0.113.82', user: 'root', port: 22, removable: true, ok: true, state: 'ok',
    hostname: 'srv1', os: 'Debian GNU/Linux 12 (bookworm)', uptime: 'up 2 weeks, 2 days, 16 hours, 4 minutes',
    ncpu: 2, load: '1.83 2.06 1.81',                                   // strings, as the probe prints them
    memory: { total: 7.8 * GB, used: 6.4 * GB, used_percent: 82 }, disk: { total: 98.2 * GB, used: 54.1 * GB, used_percent: 58 } },
  { id: 'hp', label: 'hp-laptop', host: '192.0.2.104', user: 'u', port: 2222, removable: true, ok: false, state: 'error',
    reason: 'המחשב לא הגיב בזמן' },
] };
const AUDIT = { id: 'srv', label: 'שרת פיתוח', host: '203.0.113.82', cached: false, state: 'error',
  facts: { ssh_password_auth: 'yes' }, counts: { error: 1, warn: 1, info: 0, ok: 0 }, findings: [
    { code: 'ssh_password_auth', severity: 'error', title: 'SSH מקבל סיסמאות', detail: 'PasswordAuthentication yes', fix: 'הגדר no' },
    { code: 'firewall_off', severity: 'warn', title: 'חומת האש כבויה', detail: '', fix: '' }] };
const ANSWERS = {
  'api/computers': [200, FLEET],
  'api/computers/srv/audit': [200, AUDIT],
  'api/computers/hp/audit': [502, { error: 'המחשב לא החזיר נתוני ביקורת', stderr: 'ssh: connect to host: timed out' }],
};
const sandbox = {
  document: { getElementById: el, addEventListener() {}, querySelector: () => null, hidden: false },
  window: {}, console: { warn() {}, log() {} }, setInterval: () => 0, setTimeout: () => 0,
  fetch: async (path) => {
    const hit = ANSWERS[String(path).split('?')[0]];
    if (!hit) throw new TypeError('Failed to fetch');             // what a browser throws when nothing answers
    return { ok: hit[0] < 400, status: hit[0], json: async () => hit[1] };
  },
};
vm.createContext(sandbox);
vm.runInContext(`${src}\nglobalThis.__x = { S, ACTS, load, api, uptimeHe, openAudit };`, sandbox);
const X = sandbox.__x;

let passed = 0;
function ok(cond, what) {
  if (!cond) { console.error('FAIL  ' + what); process.exit(1); }
  passed += 1;
}

await X.load(true);
const table = html('tableMount');
const row = (id) => table.split('<tr data-id="').find((r) => r.startsWith(id + '"')) || '';
const buttons = (id) => [...row(id).matchAll(/<button[^>]*class="([^"]*)"[^>]*data-act="(\w+)"[^>]*title="([^"]*)"([^>]*)>([\s\S]*?)<\/button>/g)]
  .map((m) => ({ cls: m[1].split(/\s+/).filter(Boolean), act: m[2], title: m[3], rest: m[4], body: m[5].trim() }));

/* ── a row's actions: ONE word, the rest icons that say what they do ──────────────────────────── */
const want = { local: ['auth', 'probe'], srv: ['exec', 'audit', 'probe', 'del'], hp: ['probe', 'auth', 'del'] };
for (const [id, acts] of Object.entries(want)) {
  const bs = buttons(id);
  ok(bs.map((b) => b.act).join() === acts.join(), `${id}: the actions of its state, in order (${bs.map((b) => b.act)})`);
  ok(bs[0].body === X.ACTS[acts[0]].he && !bs[0].cls.includes('ic'), `${id}: the first action is worded`);
  ok(bs.slice(1).every((b) => b.cls.includes('ic') && b.body.startsWith('<svg') && /aria-label="[^"]+"/.test(b.rest)),
     `${id}: every other action is an icon with a spoken name`);
  ok(bs.every((b) => b.title.length > 12), `${id}: every action says what will happen (title)`);
  ok(bs.every((b) => b.cls.includes('sm')), `${id}: one button family, one height`);
}
ok(buttons('local')[0].cls.includes('ghost') === false, 'a machine that waits for the owner leads with a filled button');
ok(buttons('srv').at(-1).cls.includes('danger') && buttons('hp').at(-1).cls.includes('danger'), 'the destructive action is last, and marked');
ok(!row('local').includes('data-act="del"'), "the office's own machine cannot be removed");

/* ── the cells ───────────────────────────────────────────────────────────────────────────────── */
ok((table.match(/<th>/g) || []).length === 7, 'seven columns: the address is the second line of the name');
ok(!table.includes('class="dot'), 'a state is said once (the pill), not twice');
ok(row('local').replace(/title="[^"]*"/g, '').split('המחשב הזה').length === 2, "the office's own machine is named once in its row");
ok(row('srv').includes('title="root@203.0.113.82:22"'), 'user and port are one hover away, not in the line');
ok(/class="small muted nw"><span class="num">6\.4 GB \/ 7\.8 GB</.test(row('srv')), 'used / total never breaks inside a value');
ok(row('srv').includes('1.83 · 2.06 · 1.81'), 'the load is three figures, not a raw string');
const units = (s) => (X.uptimeHe(s).match(/<bdi>/g) || []).length;
ok(units('up 2 weeks, 2 days, 16 hours, 4 minutes') === 2 && units('1440000') === 2 && units('up 3 hours, 12 minutes') === 2,
   'an uptime is its two leading units');

/* ── the security look draws what the service answered ───────────────────────────────────────── */
const threw = async (p) => { try { await p; return ''; } catch (e) { return String(e); } };
ok(!(await threw(X.openAudit('srv'))), 'the look reads the answer where the helper puts it (it does not throw)');
ok(html('auditBody').includes('SSH מקבל סיסמאות') && !html('auditBody').includes('בודק את המחשב'), 'the findings are drawn');
ok(html('auditBody').includes('שגיאה אחת, אזהרה אחת, 0 הערות'), 'counts are said in Hebrew');
ok(html('auditBody').indexOf('SSH מקבל סיסמאות') < html('auditBody').indexOf('חומת האש כבויה'), 'errors before warnings');
ok(!(await threw(X.openAudit('hp'))), 'a look that could not run does not throw either');
ok(html('auditBody').includes('המחשב לא החזיר נתוני ביקורת') && html('auditBody').includes('timed out'),
   "a look that could not run says the service's own reason, and shows ssh's words");
ok(!/HTTP \d/.test(html('auditBody')), 'never a status code as the reason');

/* ── nothing answers ─────────────────────────────────────────────────────────────────────────── */
const dead = await X.api('api/nowhere');
ok(dead.ok === false && dead.d.error && !/[A-Za-z]/.test(dead.d.error), 'a failed request is worded, with no class name in it');

console.log(`computers ui-selfcheck: ${passed} checks passed`);
