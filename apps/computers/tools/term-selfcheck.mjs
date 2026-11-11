/* term-selfcheck.mjs — the terminal screen's rule that needs neither a browser nor a machine.
 *
 * Why this exists. A keystroke and the poll can be in flight at once, both asking from the same cursor, and
 * each answer carries the same new bytes: the screen wrote both, so what a person typed was often echoed twice
 * (the second reader of DGO-1800, 2026-11-10). The rule: an answer from a cursor that has moved on since is
 * dropped, and nothing is lost by it — the next poll asks from the cursor as it is now.
 *
 * This EVALUATES THE SHIPPED SOURCE (`static/terminal/term.js`, the screen computers serves since DGO-1800) in a
 * Node VM with a small DOM stub, holds the two requests open, answers them in both orders, and reads what the
 * terminal was given to draw — and that it talks to computers' OWN routes, with no relay between. Dev tooling: the
 * image copies `*.py` and `static/` only, and gate G72 runs it.
 *
 *   node apps/computers/tools/term-selfcheck.mjs      # exits non-zero when a check fails
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'static', 'terminal', 'term.js'), 'utf8');

const els = new Map();
function el(id) {
  if (!els.has(id)) {
    els.set(id, { id, value: '', textContent: '', innerHTML: '', className: '', disabled: false, options: [],
                  children: [], appendChild() {}, addEventListener() {}, focus() {},
                  replaceChildren(...c) { this.children = c; } });
  }
  return els.get(id);
}

// fetch, held: every request waits until the check answers it
const pending = [];
const listeners = {};
const seen = [];                                             // what was asked before the race (the fleet's list)
let held = false;
function fetchStub(path, opt) {
  if (!held) {
    seen.push(path);
    return Promise.resolve({ ok: true, status: 200, json: async () => ({ computers: [
      { id: 'computer_ssh-1a2b', label: 'שרת', host: '203.0.113.5', user: 'root', port: 22, state: 'ok', ok: true },
      { id: 'computer_local-local.hp-laptop', host: 'h', state: 'ok', ok: true, remote: { office: 'hp-laptop', shell: false } },
    ], office_key: { fingerprint: 'SHA256:abc' } }) });
  }
  return new Promise((resolve) => pending.push({ path, body: opt && opt.body ? JSON.parse(opt.body) : null,
    answer: (d) => resolve({ ok: true, status: 200, json: async () => d }) }));
}

const drawn = [];
const fails = [];
function check(cond, what) {
  console.log((cond ? 'PASS  ' : 'FAIL  ') + what);
  if (!cond) fails.push(what);
}
let bootError = null;
process.on('unhandledRejection', (e) => { bootError = e; });

const ctx = vm.createContext({
  document: { getElementById: el, createElement: () => el('new' + Math.random()), body: el('body') },
  location: { search: '' }, URLSearchParams, fetch: fetchStub, console,
  setTimeout: () => 0, clearTimeout() {}, encodeURIComponent,
  addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },   // the window's own (pagehide, resize)
});
ctx.window = ctx;
vm.runInContext(src, ctx, { filename: 'term.js' });
await new Promise((r) => setImmediate(r));                         // boot: the (empty) fleet is read
await new Promise((r) => setImmediate(r));
// the first view, before a machine is chosen: it drew without throwing, and «התחברות» waits for a machine
check(!bootError, `the first view, with no machine chosen, draws without an error (${bootError && bootError.message})`);
// «התחברות» follows the choice: the screen picks the first machine that answers, so it is on — and it is off
// whenever no machine is chosen (the first view of an office with none)
check(el('btnConn').disabled === !vm.runInContext('S.machine', ctx),
      `…and «התחברות» is on exactly when a machine is chosen (${vm.runInContext('S.machine && S.machine.id', ctx)})`);
vm.runInContext('S.machine = null; paintMachine();', ctx);
check(el('btnConn').disabled === true, '…off with none chosen');
// the fleet is computers' own list, read without probing, and mapped to what the screen draws
check(seen[0] === 'api/computers?probe=0', `the machines come from computers itself (${seen[0]})`);
const ms = vm.runInContext('S.machines', ctx);
check(ms.length === 2 && ms[0].label === 'שרת' && ms[0].ssh === true && ms[1].shell === false
      && vm.runInContext('S.last', ctx) === 'SHA256:abc',
      `…mapped: label, ssh, a linked office's machine that cannot take a shell, the office key (${JSON.stringify(ms.map((m) => [m.id, m.shell]))})`);
const flush = () => new Promise((r) => setImmediate(r));

async function race(first) {
  vm.runInContext(`S.machine = {id: "m1"}; S.session = "0a1b2c3d4e5f6071"; S.cursor = 10; S.alive = true;
                   S.sending = false; S.queue = ""; S.term = {write: (s) => __drawn.push(s)};`,
                  Object.assign(ctx, { __drawn: drawn }));
  drawn.length = 0;
  pending.length = 0;
  held = true;
  vm.runInContext('poll(); sendInput("l");', ctx);
  await flush();
  // computers' own shell routes, the machine and the session in the path — no relay, no ids in a body
  const poll = pending.find((p) => p.path === 'api/computers/m1/shell/0a1b2c3d4e5f6071?cursor=10');
  const input = pending.find((p) => p.path === 'api/computers/m1/shell/0a1b2c3d4e5f6071/input');
  check(poll && input && input.body.cursor === 10 && input.body.data === 'l',
        `${first} first: both requests ask computers from cursor 10 (${pending.map((p) => p.path).join(' | ')})`);
  const echo = { cursor: 11, output: 'l', alive: true, lost: false };
  for (const p of (first === 'the keystroke' ? [input, poll] : [poll, input])) {
    p.answer(echo);
    await flush();
    await flush();
  }
  check(drawn.join('') === 'l', `${first} first: the echo is drawn once (${JSON.stringify(drawn)})`);
  check(vm.runInContext('S.cursor', ctx) === 11, `${first} first: the cursor is the answer's (11)`);
}

await race('the keystroke');
await race('the poll');

// nothing is lost by a dropped answer: the next poll asks from the cursor as it is now, and what it brings is drawn
drawn.length = 0;
pending.length = 0;
vm.runInContext('poll();', ctx);
await flush();
const next = pending[0];
check(next && next.path.includes('cursor=11'), `the next poll asks from 11 (${next && next.path})`);
if (next) {
  next.answer({ cursor: 14, output: 's -', alive: true, lost: false });
  await flush();
  await flush();
}
check(drawn.join('') === 's -', `…and what it brings is drawn (${JSON.stringify(drawn)})`);

// an answer for a session this screen no longer has — a disconnect and a new connect between — is dropped even
// when its cursor happens to equal the new one's
drawn.length = 0;
pending.length = 0;
vm.runInContext('poll();', ctx);
await flush();
const old = pending[0];
vm.runInContext('S.session = "fedcba9876543210"; S.cursor = 14;', ctx);   // a new session, at the same cursor
if (old) {
  old.answer({ cursor: 20, output: 'OLD', alive: true, lost: false });
  await flush();
  await flush();
}
check(!drawn.join('').includes('OLD') && vm.runInContext('S.cursor', ctx) === 14,
      `an answer for the session before is not drawn into the new one (${JSON.stringify(drawn)})`);

// the screen's own words never go into xterm, which has no right-to-left and draws Hebrew reversed («רבחתמ…»):
// no write() of the source carries a Hebrew letter, and a disconnect is said on the page's own line
const hebrewWrites = src.split('\n').filter((l) => /\.write\(/.test(l) && /[֐-׿]/.test(l));
check(hebrewWrites.length === 0, `no Hebrew is written into the terminal (${hebrewWrites.map((l) => l.trim()).join(' | ')})`);
drawn.length = 0;
held = false;
await vm.runInContext('disconnect(false)', ctx);
check(!/[֐-׿]/.test(drawn.join('')) && el('mHint').textContent === 'התנתקת',
      `…a disconnect draws a neutral rule and says «התנתקת» above the terminal (${JSON.stringify(el('mHint').textContent)})`);

// …and by behaviour, not only by the source's lines (a Hebrew sentence in a variable slipped past those — the second
// reader): a machine that cannot take a shell, output lost, a session that ends — nothing Hebrew reaches xterm
drawn.length = 0;
vm.runInContext(`S.machine = {id: "x", shell: false}; S.session = null;`, ctx);
await vm.runInContext('connect()', ctx);
vm.runInContext(`S.machine = {id: "m1"}; S.session = "0a1b2c3d4e5f6071"; S.cursor = 20; S.alive = true;
                 absorb({cursor: 30, output: "", lost: true, alive: false, reason: "ssh יצא"}, 20, "0a1b2c3d4e5f6071");`, ctx);
check(!/[֐-׿]/.test(drawn.join('')) && el('mHint').textContent.startsWith('הטרמינל נסגר'),
      `a machine without a shell, lost output and a session that ended are said above the terminal (${JSON.stringify(drawn)})`);

// a second session after one ended: xterm's element, which the «אין טרמינל פתוח» note took out, is put back
const element = { isConnected: false };
vm.runInContext('S.term = __t;', Object.assign(ctx, { __t: { element, write: (s) => drawn.push(s), reset() {} } }));
vm.runInContext('makeTerm();', ctx);
check(el('termMount').children[0] === element, "a second connect puts the terminal back where it is seen");

// a new machine chosen: the last session's note is not shown over its own hint
vm.runInContext(`S.session = null; S.note = "התנתקת"; S.machines = [{id: "b", state: "needs_action"}]; pick("b");`, ctx);
check(el('mHint').textContent.startsWith('מפתח הלשכה'), `choosing another machine shows its own hint (${el('mHint').textContent})`);

// leaving the page closes its session (DELETE, kept alive past the page)
vm.runInContext('S.machine = {id: "m1"}; S.session = "0a1b2c3d4e5f6071";', ctx);
seen.length = 0;
const gone = [];
ctx.fetch = (path, opt) => { gone.push([path, opt && opt.method, opt && opt.keepalive]); return Promise.resolve({}); };
for (const fn of listeners.pagehide || []) fn();
check(gone.length === 1 && gone[0][0] === 'api/computers/m1/shell/0a1b2c3d4e5f6071' && gone[0][1] === 'DELETE' && gone[0][2] === true,
      `leaving the page closes its session (${JSON.stringify(gone)})`);

console.log(`term-selfcheck: ${fails.length ? fails.length + ' FAILED' : 'ok'}`);
process.exit(fails.length ? 1 : 0);
