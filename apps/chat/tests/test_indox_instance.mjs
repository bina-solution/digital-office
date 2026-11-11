// chat names the INDOX instance its calls act on (DGO-1815). Node, no dependencies, no network:
//   node apps/chat/tests/test_indox_instance.mjs
// What holds: a declared INDOX_INSTANCE wins; else the ONE enabled instance whose purpose is not 'test', cached five
// minutes; else none, kept a minute and said once per ten minutes; a failed refresh keeps the last good id; and both
// of chat's INDOX calls send what it resolves.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { instanceResolver, instanceParams } = require(join(here, '..', 'src', 'services', 'indox_instance.js'));

let n = 0;
async function t(name, fn) { await fn(); n += 1; console.log('ok   ' + name); }

function resolver({ declared = '', answer, clock = { t: 1000 } }) {
  const asked = [];
  const warned = [];
  const get = async (url, opts) => {
    asked.push([url, opts && opts.timeout]);
    if (answer instanceof Error) throw answer;
    return { data: typeof answer === 'function' ? answer() : answer };
  };
  const r = instanceResolver({ declared, get, base: 'http://incoming-documents:8080', prefix: '/incomingDocuments',
    now: () => clock.t, warn: (s) => warned.push(s) });
  return { r, asked, warned, clock };
}

await t('a declared INDOX_INSTANCE wins, and INDOX is not asked', async () => {
  const { r, asked } = resolver({ declared: 'example', answer: { instances: [{ id: 'other', enabled: true }] } });
  assert.equal(await r(), 'example');
  assert.deepEqual(asked, []);
  assert.deepEqual(await instanceParams(r), { instance: 'example' });
});

await t('a declaration that is not an instance id names none, and says so', async () => {
  const { r, warned } = resolver({ declared: 'Ha example', answer: { instances: [] } });
  assert.equal(await r(), '');
  assert.equal(warned.length, 1);
});

// what every office's registry holds (platform.state.default.yaml): its own tenant and the standing `test` one
const REAL = { success: true, instances: [
  { id: 'example', schema_name: 'indox_example', label: 'הדוגמה', enabled: true, purpose: '' },
  { id: 'test', schema_name: 'indox_test', label: 'בדיקות', enabled: true, purpose: 'test' },
  { id: 'old', schema_name: 'indox_old', label: 'ישן', enabled: false, purpose: '' }] };

await t("else the one enabled instance whose purpose is not 'test', asked at /instances, cached five minutes", async () => {
  const { r, asked, clock } = resolver({ answer: REAL });
  assert.equal(await r(), 'example');
  assert.deepEqual(asked, [['http://incoming-documents:8080/incomingDocuments/instances', 10000]]);
  clock.t += 4 * 60 * 1000;
  assert.equal(await r(), 'example');
  assert.equal(asked.length, 1, 'cached');
  clock.t += 2 * 60 * 1000;
  await r();
  assert.equal(asked.length, 2, 'asked again after five minutes');
});

await t('two production instances, or none, name none — kept a minute, said once per ten minutes', async () => {
  const two = { instances: [...REAL.instances, { id: 'exampleu', enabled: true, purpose: '' }] };
  const { r, asked, warned, clock } = resolver({ answer: two });
  assert.equal(await r(), '');
  assert.equal(await r(), '');
  assert.equal(asked.length, 1, 'a miss is kept for a minute, not asked per post');
  clock.t += 61 * 1000;
  assert.equal(await r(), '');
  assert.equal(asked.length, 2, 'asked again after a minute');
  assert.equal(warned.length, 1, 'said once');
  clock.t += 11 * 60 * 1000;
  await r();
  assert.equal(warned.length, 2);
  assert.match(warned[0], /2 enabled production instances/);
  assert.deepEqual(await instanceParams(r), {});
});

await t('an INDOX that does not say purpose: its tenant and `test` are two, so none is named', async () => {
  const older = { instances: REAL.instances.map(({ purpose, ...x }) => x) };
  assert.equal(await resolver({ answer: older }).r(), '');
});

await t('a failed or odd answer names none, kept a minute, then asked again', async () => {
  const failed = resolver({ answer: new Error('ECONNREFUSED') });
  assert.equal(await failed.r(), '');
  assert.equal(await failed.r(), '');
  assert.equal(failed.asked.length, 1);
  failed.clock.t += 61 * 1000;
  await failed.r();
  assert.equal(failed.asked.length, 2);
  const odd = resolver({ answer: { instances: [{ id: 'Bad Id', enabled: true }] } });
  assert.equal(await odd.r(), '');
});

await t('a failed refresh keeps the last good id; a registry that answers with two drops it', async () => {
  let answer = REAL;
  const { r, asked, clock } = resolver({ answer: () => { if (answer instanceof Error) throw answer; return answer; } });
  assert.equal(await r(), 'example');
  clock.t += 6 * 60 * 1000;
  answer = new Error('ETIMEDOUT');
  assert.equal(await r(), 'example', 'INDOX down: the good id stays');
  assert.equal(asked.length, 2);
  assert.equal(await r(), 'example', 'and is not asked again within the minute');
  assert.equal(asked.length, 2);
  clock.t += 61 * 1000;
  answer = { instances: [...REAL.instances, { id: 'exampleu', enabled: true, purpose: '' }] };
  assert.equal(await r(), '', 'the registry answered with two: no single tenant any more');
});

await t("INDOX's /instances says each instance's purpose", async () => {
  const py = readFileSync(join(here, '..', '..', 'indox', 'app', 'incoming_documents', 'api', '__init__.py'), 'utf8');
  const body = py.slice(py.indexOf('def list_instance_registry'), py.indexOf('def list_instance_tables'));
  assert.match(body, /coalesce\(purpose, ''\) as purpose/);
});

await t("both of chat's INDOX calls send the resolved instance", async () => {
  for (const f of ['incoming_documents_api.js', 'companies_api.js']) {
    const src = readFileSync(join(here, '..', 'src', 'services', f), 'utf8');
    assert.match(src, /require\('\.\/indox_instance'\)/, f);
    assert.match(src, /params: await instanceParams\(defaultResolver\(\)\)/, f);
  }
});

console.log(`${n} checks hold`);
