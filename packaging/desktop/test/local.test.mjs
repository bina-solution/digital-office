// node --test packaging/desktop/test/*.test.mjs (or `npm test` there) — «the office on this computer» is said only of
// an office: src/local.js running() reads the probe's answer as every typed address is read (offices.js readProbe).
// Any answer under 500 used to count, and a clean Windows machine with something else on port 80 was told its office
// was running (the first installers' proof picture, v0.3.5, 2026-11-24, DGO-2188).
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const local = require('../src/local.js');
const { PROBE_PATH } = require('../src/offices.js');

const answering = (answer) => async (url) => {
  assert.equal(url, `${local.ORIGIN}${PROBE_PATH}`);   // the one question: this computer's console, its office's record
  return answer;
};

test('an office behind its sign-in is running: the edge sends the probe to a /login that comes back here', async () => {
  const location = `http://auth.localhost/login?rd=${encodeURIComponent(`${local.ORIGIN}${PROBE_PATH}`)}`;
  assert.equal(await local.running(answering({ status: 302, location })), true);
});

test("an office with no sign-in in front is running: the console answers its office's record", async () => {
  assert.equal(await local.running(answering({ status: 200, json: { office: { name: 'הלשכה' }, installed: true } })), true);
});

test('another web server on port 80 is no office: a 404, a page, a redirect elsewhere, a JSON that is not the record', async () => {
  for (const answer of [
    { status: 404 },
    { status: 200, json: null },
    { status: 200, json: { hello: 1 } },
    { status: 301, location: 'https://example.com/' },
    { status: 302, location: 'http://auth.localhost/login?rd=https%3A%2F%2Fother.example%2F' },
    { status: 401 },
  ]) assert.equal(await local.running(answering(answer)), false, JSON.stringify(answer));
});

test('nothing answers, or the engine is starting: not running', async () => {
  assert.equal(await local.running(answering({ status: 0, error: 'unreachable' })), false);
  assert.equal(await local.running(answering({ status: 502 })), false);
  assert.equal(await local.running(answering(undefined)), false);
});

test('a sign-in named by a path alone is this office\'s; a redirect to the same page over https is not a sign-in', async () => {
  const rd = encodeURIComponent(`${local.ORIGIN}${PROBE_PATH}`);
  assert.equal(await local.running(answering({ status: 302, location: `/login?rd=${rd}` })), true);
  assert.equal(await local.running(answering({ status: 301, location: `https://console.localhost${PROBE_PATH}` })), false);
});

test('after `dgo run`: asked again until the office answers as one — its edge answers 404 before its console does', async () => {
  const location = `http://auth.localhost/login?rd=${encodeURIComponent(`${local.ORIGIN}${PROBE_PATH}`)}`;
  const answers = [{ status: 0, error: 'unreachable' }, { status: 404 }, { status: 404 }, { status: 302, location }];
  let asked = 0; const slept = [];
  const up = await local.comesUp(async () => answers[Math.min(asked++, answers.length - 1)],
    { tries: 30, gapMs: 2000, sleep: async (ms) => { slept.push(ms); } });
  assert.equal(up, true);
  assert.equal(asked, 4);
  assert.deepEqual(slept, [2000, 2000, 2000]);
});

test('…and given up after its tries, with no sleep after the last one', async () => {
  let asked = 0; const slept = [];
  const up = await local.comesUp(async () => { asked++; return { status: 404 }; },
    { tries: 5, gapMs: 10, sleep: async (ms) => { slept.push(ms); } });
  assert.equal(up, false);
  assert.equal(asked, 5);
  assert.equal(slept.length, 4);
});
