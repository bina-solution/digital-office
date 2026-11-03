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
  { id: 'nas', label: 'NAS', host: '192.0.2.50', user: 'admin', port: 22, removable: true, ok: false, state: 'needs_action',
    reason: 'המפתח של הלשכה עדיין לא אושר במחשב' },
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
// THE SANDBOX IS THE BROWSER THE APP IS WRITTEN FOR. It had no `location`, no `history` and not even
// `URL` — and since 2026-10-13 the app reads its own route out of the address
// (`document.baseURI` + `location.pathname`, "the address is the state"), so the check died on its
// first line with `ReferenceError: URL is not defined` and said nothing about anything else. It was
// red in gate G72 for a day, which is how a broken check hides a broken app.
const wrote = [];
// `history.replaceState` MOVES THE ADDRESS in a browser, and this stub does too: the app decides
// whether to write by comparing the address it is about to write with the one it is on, so a stub
// that only records left the app on its old path and the second write never happened.
const loc = { pathname: '/a/computers/', search: '', href: 'http://localhost/a/computers/',
              origin: 'http://localhost' };
const nav = (u) => {
  wrote.push(u);
  const [p, q] = String(u).split('?');
  loc.pathname = p;
  loc.search = q ? '?' + q : '';
};
const sandbox = {
  URL,
  document: { getElementById: el, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [], hidden: false,
              baseURI: 'http://localhost/a/computers/' },
  location: loc,
  history: { replaceState: (_s, _t, u) => nav(u), pushState: (_s, _t, u) => nav(u) },
  window: { addEventListener() {}, removeEventListener() {} }, console: { warn() {}, log() {} },
  setInterval: () => 0, setTimeout: () => 0,
  fetch: async (path) => {
    const hit = ANSWERS[String(path).split('?')[0]];
    if (!hit) throw new TypeError('Failed to fetch');             // what a browser throws when nothing answers
    return { ok: hit[0] < 400, status: hit[0], json: async () => hit[1] };
  },
};
vm.createContext(sandbox);
vm.runInContext(`${src}\nglobalThis.__x = { S, ACTS, load, api, uptimeHe, openAudit, routeOf, showRoute, match, render };`, sandbox);
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
const want = { srv: ['exec', 'audit', 'probe', 'del'], hp: ['probe', 'auth', 'del'], nas: ['auth', 'probe', 'del'] };
for (const [id, acts] of Object.entries(want)) {
  const bs = buttons(id);
  ok(bs.map((b) => b.act).join() === acts.join(), `${id}: the actions of its state, in order (${bs.map((b) => b.act)})`);
  ok(bs[0].body === X.ACTS[acts[0]].he && !bs[0].cls.includes('ic'), `${id}: the first action is worded`);
  ok(bs.slice(1).every((b) => b.cls.includes('ic') && b.body.startsWith('<svg') && /aria-label="[^"]+"/.test(b.rest)),
     `${id}: every other action is an icon with a spoken name`);
  ok(bs.every((b) => b.title.length > 12), `${id}: every action says what will happen (title)`);
  ok(bs.every((b) => b.cls.includes('sm')), `${id}: one button family, one height`);
}
ok(buttons('nas')[0].cls.includes('ghost') === false, 'a machine that waits for the owner leads with a filled button');
ok(buttons('srv').at(-1).cls.includes('danger') && buttons('hp').at(-1).cls.includes('danger'), 'the destructive action is last, and marked');
ok(!row('local'), "the office's own machine is its herd row («המחשב הזה»), not a second row in the SSH list");
ok(X.S.sshOf.local && X.S.sshOf.local.id === 'local', "…its SSH access is folded into that row");
ok(html('alerts').includes('ממתין לאישור מפתח ה־SSH של הלשכה') && html('alerts').includes('„גישה”'),
   "a folded machine that waits for its key says where the command is (its page, «גישה»)");

/* ── the cells ───────────────────────────────────────────────────────────────────────────────── */
ok((table.match(/<th>/g) || []).length === 7, 'seven columns: the address is the second line of the name');
ok(!table.includes('class="dot'), 'a state is said once (the pill), not twice');
ok(row('srv').includes('title="root@203.0.113.82:22"'), 'user and port are one hover away, not in the line');
ok(/class="small muted nw"><span class="num">6\.4 GB \/ 7\.8 GB</.test(row('srv')), 'used / total never breaks inside a value');
ok(row('srv').includes('1.83 · 2.06 · 1.81'), 'the load is three figures, not a raw string');
const units = (s) => (X.uptimeHe(s).match(/<bdi>/g) || []).length;
ok(units('up 2 weeks, 2 days, 16 hours, 4 minutes') === 2 && units('1440000') === 2 && units('up 3 hours, 12 minutes') === 2,
   'an uptime is its two leading units');

/* ── the herd: one row per computer (DGO-890) ────────────────────────────────────────────────── */
const OV = { host: { hostname: 'lima-bbox', os: 'Ubuntu 24.04 LTS', kernel: '6.8', uptime_seconds: 90000 },
  cpu: { percent: 23, cores: 8, load1: 1.1, load5: 1, load15: 0.9, model: 'Apple M2' },
  memory: { percent: 61, used: 5 * GB, total: 8 * GB }, storage: { root: { percent: 44, free: 50 * GB } },
  docker: { containers_running: 28, containers_total: 31, containers_unhealthy: 0 }, net_rate: { rx: 1, tx: 1 }, history: [] };
X.S.herd = [
  { where: 'local', office: 'macbook', label: 'המחשב הזה', local: true, gives: { machine: false, security: true } },
  { where: 'vps1', office: 'vps1', label: 'שרת פיתוח', local: false, gives: { machine: true, security: false } },
];
X.S.hd = { local: { ov: OV, src: 'security', at: Date.now(), err: '', sum: { kpi: { requests: 55, out_dests: 12, bans: 0, would_ban: 0 } } },
           vps1: { at: 1, err: 'אין דרך למחשב הזה כרגע', sumErr: 'הלשכה הזאת לא נותנת את השירות הזה דרך הקישור' } };
X.match();
X.render();
const herdHtml = html('herdMount');
const hrow = (where) => herdHtml.split('<a class="hrow"').find((r) => r.includes(`data-where="${where}"`)) || '';
ok((herdHtml.match(/<a class="hrow"/g) || []).length === 2, 'one row per computer of the herd');
ok(hrow('local').includes('href="c/local"') && hrow('vps1').includes('href="c/vps1"'), 'a row opens its computer: a link under the mount (keyboard and a new tab work)');
ok(hrow('local').includes('הלשכה הזאת') && hrow('local').includes('lima-bbox') && hrow('local').includes('>23%<'),
   "this office's row: named, its hostname, its live processor share");
ok(hrow('local').includes('ממתין לאישור'), "…and the SSH state of the machine folded into it");
ok(X.S.sshOf.vps1 && X.S.sshOf.vps1.id === 'srv' && !html('tableMount').includes('data-id="srv"'),
   "a linked office's SSH machine (matched by name) leaves the SSH list and lives in that office's row");
ok(hrow('vps1').includes('לא עונה') && hrow('vps1').includes('אין דרך למחשב הזה כרגע'), 'an office that does not answer says so, with the reason one hover away');
ok(hrow('vps1').includes('אין אבטחה'), 'an office without the security app says so instead of zeros');
ok(!/undefined|NaN|\[object/.test(herdHtml), 'no raw value leaks into a row');

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

/* ── the address IS the state: the mount from baseURI, the route from the path ─────────────────── */
// The sandbox serves the app the way the console does (`/a/computers/`), so the same paths a person
// copies are what is measured here: `/a/computers/hp` is the machine's dialog, the mount itself is
// the fleet table, and opening a dialog writes that address back.
sandbox.location.pathname = '/a/computers/hp';
ok(X.routeOf() === 'hp', "a machine's dialog is the machine named in the path, under this app's mount");
sandbox.location.pathname = '/a/computers/';
ok(X.routeOf() === '', 'the mount itself is the fleet table (no dialog)');
sandbox.location.pathname = '/elsewhere/hp';
ok(X.routeOf() === '', 'a path outside this app is not a route of this app');
sandbox.location.pathname = '/a/computers/';
wrote.length = 0;
X.showRoute('srv', true);
ok(wrote.at(-1) === '/a/computers/srv', 'opening a dialog writes its address (replace, so history stays clean)');
wrote.length = 0;
X.showRoute('', true);
ok(wrote.at(-1) === '/a/computers/', 'and closing it writes the mount back');

/* ── a computer of the herd has an address too: `/c/<where>/<tab>` under the mount ─────────────── */
sandbox.location.pathname = '/a/computers/c/vps1/net';
ok(X.routeOf() === 'c/vps1/net', "a computer's page is in the path, with its tab");
sandbox.location.pathname = '/a/computers/';
wrote.length = 0;
X.showRoute('c/vps1/disk');
ok(wrote.at(-1) === '/a/computers/c/vps1/disk', "a computer's page writes its address segment by segment (no %2F)");
ok(!/#\/c\//.test(src) && !/location\.hash\s*=/.test(src.replace(/window\.top\.location\.hash/g, '')),
   'no screen of this app lives in the hash: the console mirrors the path only (G83)');

console.log(`computers ui-selfcheck: ${passed} checks passed`);
