/* test_bina_said.mjs — the shared block's own promises, executed.
 *
 *   node platform-base/bina-ui/test_bina_said.mjs
 *
 * `bina-said.js` names a failed request for a person. What it must never do is the thing it
 * replaced: put the wire's word on the screen. So every status a service can answer with is asked
 * for, and the answer has to be a Hebrew sentence with no code, no English and no digit in it.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'bina-said.js'), 'utf8');
const box = {};
vm.createContext(box);
vm.runInContext(src, box);                       // `var` on purpose: two screens on one page may both carry it
vm.runInContext(src, box);                       // …so loading it twice is not an error
const { binaSaid, binaNoAnswer } = box;

let passed = 0;
function ok(cond, what) {
  if (!cond) { console.error('FAIL  ' + what); process.exit(1); }
  passed += 1;
}

const statuses = [0, undefined, null, 200, 204, 400, 401, 403, 404, 405, 409, 422, 429, 500, 501, 502, 503, 504, 520];
for (const s of statuses) {
  const said = binaSaid(s);
  ok(typeof said === 'string' && /[א-ת]/.test(said) && !/[A-Za-z0-9]/.test(said), `status ${s} is said in Hebrew, with no code in it (${said})`);
}
ok(binaSaid(0) === binaSaid(undefined), 'nothing answered is one sentence, whether the status is 0 or absent');
ok(binaSaid(502) === binaSaid(503) && binaSaid(503) === binaSaid(504) && binaSaid(502) !== binaSaid(500),
   'a service that is away (the edge answered for it) is not a service that broke');
ok(binaSaid(401) !== binaSaid(403) && binaSaid(401).includes('רענן'), 'a sign-in that ran out says what to do; a refusal does not pretend to');
ok(new Set([0, 200, 401, 403, 404, 500, 502, 400].map(binaSaid)).size === 8, 'eight situations, eight sentences');

const none = binaNoAnswer();
ok(none.ok === false && none.status === 0, 'a request that was never answered is a refusal with status 0');
ok(JSON.stringify(await none.json()) === '{}' && (await none.text()) === '', '…whose body reads as empty, both ways');
const r = await Promise.reject(new TypeError('Failed to fetch')).catch(binaNoAnswer);
ok(binaSaid(r.status) === binaSaid(0), "what fetch throws never reaches the line: it becomes «" + binaSaid(0) + "»");

console.log(`bina-said: ${passed} checks passed`);
