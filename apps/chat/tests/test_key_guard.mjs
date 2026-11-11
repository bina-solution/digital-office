// test_key_guard.mjs — chatapi's guard passes a key-shaped header only when it IS a key: active, and an admin's.
//
//     node apps/chat/tests/test_key_guard.mjs
//
// The defect (issues/chat-opens-fifteen-routes-…): `guard = keyFrom(req) ? next() : sessionGuard(…)` let any
// `Authorization: Bearer x` past the session guard, on the understanding that `withActor` checks the key next —
// and fifteen routes (accounts, bots' settings, connections) use `guard` alone. What holds now:
//   1. no key → the session guard, exactly as before (it decides);
//   2. an unknown key → 401; an inactive profile's → 403; a non-admin's → 403; an active admin's → passes;
//   3. every key shape is resolved: X-Chat-Profile-Key, Authorization: Bearer, body.profile_key;
//   4. a profile store that cannot answer → 503, never a pass;
//   5. server.js puts the fifteen on `adminKeyGuard`; the routes left on the pass-through `guard` all call
//      withActor, where a non-admin's key still acts as its own profile.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeKeyGuard } = require(join(here, '..', 'chatapi', 'engine', 'auth.js'));

const PROFILES = {
  'chatp_admin': { id: 'admin', is_admin: true, status: 'active' },
  'chatp_user': { id: 'user2', is_admin: false, status: 'active' },
  'chatp_off': { id: 'old', is_admin: true, status: 'disabled' },
};
const store = { byKey: async (k) => PROFILES[k] || null };

function res() {
  const r = { code: 0, body: undefined };
  r.status = (c) => { r.code = c; return r; };
  r.json = (b) => { r.body = b; return r; };
  return r;
}

async function run(guard, req) {
  const out = res();
  let passed = false;
  await guard({ headers: {}, body: {}, ...req }, out, () => { passed = true; });
  return { passed, code: out.code, body: out.body };
}

let sessionCalls = 0;
const session = (req, res, next) => { sessionCalls += 1; return res.status(401).json({ error: 'no session' }); };
const guard = makeKeyGuard({ profiles: store, sessionGuard: session });

let n = 0;
async function t(name, fn) { await fn(); n += 1; console.log('ok   ' + name); }

await t('no key: the session guard decides, as before', async () => {
  sessionCalls = 0;
  const r = await run(guard, {});
  assert.equal(sessionCalls, 1);
  assert.equal(r.code, 401);
  assert.equal(r.body.error, 'no session');
});

await t('an unknown key is refused: 401 (it used to pass)', async () => {
  const r = await run(guard, { headers: { authorization: 'Bearer x' } });
  assert.equal(r.passed, false);
  assert.equal(r.code, 401);
  assert.match(r.body.error, /unknown profile key/);
});

await t("an inactive profile's key is refused: 403", async () => {
  const r = await run(guard, { headers: { 'x-chat-profile-key': 'chatp_off' } });
  assert.equal(r.code, 403);
  assert.match(r.body.error, /not active/);
});

await t("a non-admin's key is refused on these routes: 403", async () => {
  const r = await run(guard, { headers: { 'x-chat-profile-key': 'chatp_user' } });
  assert.equal(r.code, 403);
  assert.match(r.body.error, /admin/);
});

await t("an active admin's key passes, in every shape", async () => {
  sessionCalls = 0;
  for (const req of [{ headers: { 'x-chat-profile-key': 'chatp_admin' } },
    { headers: { authorization: 'Bearer REDACTED' } },
    { body: { profile_key: 'chatp_admin' } }]) {
    assert.equal((await run(guard, req)).passed, true, JSON.stringify(req));
  }
  assert.equal(sessionCalls, 0, 'a key never falls through to the session guard');
});

await t('a store that cannot answer is a 503, never a pass', async () => {
  const broken = makeKeyGuard({ profiles: { byKey: async () => { throw new Error('db down'); } }, sessionGuard: session });
  const r = await run(broken, { headers: { authorization: 'Bearer REDACTED' } });
  assert.equal(r.passed, false);
  assert.equal(r.code, 503);
});

await t('no session guard given: a keyless request passes (the route tests\' harness), a key is still checked', async () => {
  const open = makeKeyGuard({ profiles: store, sessionGuard: null });
  assert.equal((await run(open, {})).passed, true);
  assert.equal((await run(open, { headers: { authorization: 'Bearer x' } })).code, 401);
});

await t('server.js: the fifteen use adminKeyGuard, and every route left on the pass-through guard calls withActor', async () => {
  const src = readFileSync(join(here, '..', 'chatapi', 'server.js'), 'utf8');
  assert.match(src, /const adminKeyGuard = makeKeyGuard\(/);
  // the second reader: `guard` is on 33 routes, and 18 of them call withActor, where a non-admin's key reads its
  // own conversations — the admin rule belongs to the fifteen only
  const onGuard = src.split('\n').filter((l) => /app\.(get|post|put|delete|patch)\(.*, guard,/.test(l));
  assert.ok(onGuard.length >= 10, `scan found ${onGuard.length} routes on guard`);
  for (const l of onGuard) assert.ok(l.includes('withActor'), `a route on the pass-through guard has no withActor: ${l.trim()}`);
  const routes = [
    ["get", "'/api/accounts'"], ["post", "'/api/account/select'"], ["get", "['/api/chat-providers', '/providers']"],
    ["post", "'/api/account/add'"], ["delete", "'/api/account/:id'"], ["get", "'/api/account/:id/probe'"],
    ["get", "'/api/bots'"], ["get", "'/api/bots/:id/settings'"], ["put", "'/api/bots/:id/settings'"],
    ["delete", "'/api/bots/:id/settings'"], ["post", "'/api/account/bot'"], ["get", "'/connections'"],
    ["post", "'/connections/select'"], ["post", "'/connections'"], ["delete", "'/connections/:id'"],
  ];
  for (const [m, p] of routes) {
    assert.ok(src.includes(`app.${m}(${p}, adminKeyGuard,`), `${m} ${p} uses adminKeyGuard`);
  }
});

console.log(`${n} checks hold`);
