/* term-selfcheck.mjs — the terminal screen's rule that needs neither a browser nor a machine.
 *
 * Why this exists. A keystroke and the poll can be in flight at once, both asking from the same cursor, and
 * each answer carries the same new bytes: the screen wrote both, so what a person typed was often echoed twice
 * (the second reader of DGO-1800, 2026-11-10). The rule: an answer from a cursor that has moved on since is
 * dropped, and nothing is lost by it — the next poll asks from the cursor as it is now.
 *
 * This EVALUATES THE SHIPPED SOURCE (`static/term.js`) in a Node VM with a small DOM stub, holds the two
 * requests open, answers them in both orders, and reads what the terminal was given to draw. Dev tooling: the
 * image copies `*.py` and `static/` only, and gate G72 runs it.
 *
 *   node apps/terminal/tools/term-selfcheck.mjs      # exits non-zero when a check fails
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'static', 'term.js'), 'utf8');

const els = new Map();
function el(id) {
  if (!els.has(id)) {
    els.set(id, { id, value: '', textContent: '', innerHTML: '', className: '', disabled: false, options: [],
                  appendChild() {}, addEventListener() {}, focus() {} });
  }
  return els.get(id);
}

// fetch, held: every request waits until the check answers it
const pending = [];
let held = false;
function fetchStub(path, opt) {
  if (!held) return Promise.resolve({ ok: true, status: 200, json: async () => ({ machines: [] }) });
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
});
ctx.window = ctx;
vm.runInContext(src, ctx, { filename: 'term.js' });
await new Promise((r) => setImmediate(r));                         // boot: the (empty) fleet is read
await new Promise((r) => setImmediate(r));
// the first view, before a machine is chosen: it drew without throwing, and «התחברות» waits for a machine
check(!bootError, `the first view, with no machine chosen, draws without an error (${bootError && bootError.message})`);
check(el('btnConn').disabled === true, '…and «התחברות» is disabled until a machine is chosen');
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
  const poll = pending.find((p) => p.path.startsWith('api/shell/poll'));
  const input = pending.find((p) => p.path === 'api/shell/input');
  check(poll && input && poll.path.includes('cursor=10') && input.body.cursor === 10,
        `${first} first: both requests ask from cursor 10`);
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

console.log(`term-selfcheck: ${fails.length ? fails.length + ' FAILED' : 'ok'}`);
process.exit(fails.length ? 1 : 0);
