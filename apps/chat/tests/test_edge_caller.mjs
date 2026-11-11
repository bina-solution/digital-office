// test_edge_caller.mjs — under edge trust, chat believes a caller only from the edge's hops, the office token, the
// office's Basic credential, or loopback.
//
//     node apps/chat/tests/test_edge_caller.mjs
//
// The defect (issues/chat-lets-any-caller-in-…): with TRUST_EDGE_AUTH=true `isAuthenticated` let every request
// through; on vps1 another container got 200 from GET /api/subscribers with no identity. What holds now:
//   1. a direct call with no identity is refused under enforce (401 on /api/, 403 elsewhere), and NAMED but
//      answered under warn — the default, so the offices' logs list the callers before anything is refused;
//   2. an identity header counts only from traefik's, the console's or the link door's address; typed by anyone
//      else it is refused; X-Forwarded-For cannot make a caller the edge (the peer is the socket's);
//   3. the office token (X-Chat-Office-Token) is a service; a Bearer is not (chat reads it as a profile key);
//      the office's Basic credential is believed, never while the password is the shipped fallback;
//   4. loopback is the container itself;
//   5. an unproved caller is named once per route and peer per window; an unknown mode is named and means warn;
//   6. DNS is asked only when an identity header arrives from outside, once per refresh for all requests;
//   7. auth.js routes edge trust through this check (it used to call next() unread).
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const edge = require(join(here, '..', 'src', 'api', 'middleware', 'edge_caller.js'));

const TRAEFIK = '172.18.0.2';
const CONSOLE = '172.18.0.3';
const DOOR = '172.18.0.4';
const MAILBOXD = '172.18.0.9';
let lookups = 0;
const lookup = async (name) => {
  lookups += 1;
  const at = { 'traefik-staging': TRAEFIK, 'console-staging': CONSOLE, 'dgo-net-staging': DOOR }[name];
  if (!at) throw new Error('ENOTFOUND ' + name);
  return [{ address: at, family: 4 }];
};

function req({ peer, path = '/api/subscribers', method = 'GET', headers = {}, route }) {
  return { method, path, url: path, headers, socket: { remoteAddress: peer }, route };
}

function res() {
  const r = { code: 0, body: undefined };
  r.status = (c) => { r.code = c; return r; };
  r.json = (b) => { r.body = b; return r; };
  r.send = (b) => { r.body = b; return r; };
  return r;
}

async function run(mw, request) {
  const out = res();
  let passed = false;
  await mw(request, out, () => { passed = true; });
  return { passed, code: out.code, body: out.body };
}

function check(mode, { token = 'tok-123', readToken = 'read-456', now, basic, look = lookup } = {}) {
  const lines = [];
  const mw = edge.middleware({ mode, deployment: 'staging', token, readToken, lookup: look, now, basic,
    log: { warn: (s) => lines.push(s) } });
  return { mw, lines };
}

let n = 0;
async function t(name, fn) { await fn(); n += 1; console.log('ok   ' + name); }

await t('a direct call with no identity is refused under enforce: 401 on /api/', async () => {
  const { mw, lines } = check('enforce');
  const r = await run(mw, req({ peer: MAILBOXD }));
  assert.equal(r.passed, false);
  assert.equal(r.code, 401);
  assert.match(r.body.why, /no identity/);
  assert.equal(lines.length, 1);
  assert.match(lines[0], /^chat-unproved-caller: GET "\/api\/subscribers" peer=172\.18\.0\.9 .*\(refused\)$/);
});

await t('outside /api/ the refusal is a 403', async () => {
  const { mw } = check('enforce');
  const r = await run(mw, req({ peer: MAILBOXD, path: '/' }));
  assert.equal(r.code, 403);
});

await t('warn is the default: the same call is answered and named', async () => {
  for (const mode of [undefined, '', 'warn', ' WARN ']) {
    const { mw, lines } = check(mode);
    const r = await run(mw, req({ peer: MAILBOXD, path: '/api/bot/broadcast', method: 'POST' }));
    assert.equal(r.passed, true, String(mode));
    assert.equal(lines.length, 1, String(mode));
    assert.match(lines[0], /POST "\/api\/bot\/broadcast" .*let through: CHAT_CALLER_MODE=warn/);
  }
});

await t('an unknown mode is named at start and means warn', async () => {
  const { mw, lines } = check('enforced');
  assert.equal(lines.length, 1);
  assert.match(lines[0], /^chat-caller-mode: CHAT_CALLER_MODE="enforced" is not warn or enforce — using warn$/);
  assert.equal((await run(mw, req({ peer: MAILBOXD }))).passed, true);
});

await t('a person through traefik, the console or the link door is believed', async () => {
  const { mw, lines } = check('enforce');
  for (const peer of [TRAEFIK, '::ffff:' + CONSOLE, DOOR]) {
    const r = await run(mw, req({ peer, headers: { 'x-authentik-username': 'owner' } }));
    assert.equal(r.passed, true, peer);
  }
  assert.equal(lines.length, 0);
});

await t('an identity header typed by another container is refused', async () => {
  const { mw } = check('enforce');
  const r = await run(mw, req({ peer: MAILBOXD, headers: { 'x-authentik-username': 'owner' } }));
  assert.equal(r.code, 401);
  assert.match(r.body.why, /not the edge/);
});

await t('X-Forwarded-For naming traefik does not make a container the edge', async () => {
  const { mw } = check('enforce');
  const r = await run(mw, { ...req({ peer: MAILBOXD,
    headers: { 'x-authentik-username': 'owner', 'x-forwarded-for': TRAEFIK } }), ip: TRAEFIK });
  assert.equal(r.passed, false);
});

await t('the office token is a service; a wrong or empty token is not', async () => {
  const { mw } = check('enforce');
  const H = edge.TOKEN_HEADER;
  assert.equal(H, 'x-chat-office-token');
  assert.equal((await run(mw, req({ peer: MAILBOXD, headers: { [H]: 'tok-123' } }))).passed, true);
  const wrong = await run(mw, req({ peer: MAILBOXD, headers: { [H]: 'tok-124' } }));
  assert.equal(wrong.code, 401);
  assert.match(wrong.body.why, /not this office's chat token/);
  const none = check('enforce', { token: '' });
  assert.equal((await run(none.mw, req({ peer: MAILBOXD, headers: { [H]: '' } }))).passed, false);
});

await t('a Bearer is not the office token: chat reads a Bearer as a LOCAL-chat profile key', async () => {
  const { mw } = check('enforce');
  const r = await run(mw, req({ peer: MAILBOXD, headers: { authorization: 'Bearer tok-123' } }));
  assert.equal(r.passed, false);
  assert.match(r.body.why, /no identity/);
});

await t('the office Basic credential is believed on /api/; another, or off /api/, is not', async () => {
  const parse = (r) => { const m = /^Basic (\w+):(\w+)$/.exec(r.headers.authorization || ''); return m && { name: m[1], pass: m[2] }; };
  const basic = edge.basicChecker({ username: 'admin', password: 's3cret', parse });
  const { mw } = check('enforce', { basic });
  assert.equal((await run(mw, req({ peer: MAILBOXD, headers: { authorization: 'Basic admin:s3cret' } }))).passed, true);
  assert.equal((await run(mw, req({ peer: MAILBOXD, headers: { authorization: 'Basic admin:other' } }))).passed, false);
  assert.equal((await run(mw, req({ peer: MAILBOXD, path: '/', headers: { authorization: 'Basic admin:s3cret' } }))).passed, false);
});

await t('Basic is never proof while the password is the shipped fallback (1234 or empty)', async () => {
  const parse = (r) => { const m = /^Basic (\w+):(\w*)$/.exec(r.headers.authorization || ''); return m && { name: m[1], pass: m[2] }; };
  for (const password of ['1234', '', undefined]) {
    const basic = edge.basicChecker({ username: 'admin', password, parse });
    const { mw } = check('enforce', { basic });
    const r = await run(mw, req({ peer: MAILBOXD, headers: { authorization: `Basic admin:${password || ''}` } }));
    assert.equal(r.passed, false, String(password));
  }
});

await t('loopback is the container itself', async () => {
  const { mw } = check('enforce');
  for (const peer of ['127.0.0.1', '::1', '::ffff:127.0.0.1']) {
    assert.equal((await run(mw, req({ peer }))).passed, true, peer);
  }
});

await t('an unproved caller is named once per route and peer per ten minutes, whatever its agent', async () => {
  let clock = 1_000_000;
  const { mw, lines } = check('warn', { now: () => clock });
  for (let i = 0; i < 5; i += 1) {
    // Express sets req.route to the matched Route, whose .path is the pattern
    await run(mw, req({ peer: MAILBOXD, path: `/api/conversation/${i}`, route: { path: '/api/conversation/:id' },
      headers: { 'user-agent': `agent-${i}` } }));
  }
  assert.equal(lines.length, 1);
  clock += 10 * 60 * 1000 + 1;
  await run(mw, req({ peer: MAILBOXD, path: '/api/conversation/9', route: { path: '/api/conversation/:id' } }));
  assert.equal(lines.length, 2);
});

await t('a hop that does not resolve proves nothing', async () => {
  const mw = edge.middleware({ mode: 'enforce', deployment: 'other', token: '', lookup, log: { warn() {} } });
  const r = await run(mw, req({ peer: TRAEFIK, headers: { 'x-authentik-username': 'owner' } }));
  assert.equal(r.passed, false);
});

await t('DNS is asked only for an identity header from outside, and once per refresh for every request', async () => {
  lookups = 0;
  const { mw } = check('enforce', { basic: () => true });
  await run(mw, req({ peer: '127.0.0.1', headers: { 'x-authentik-username': 'owner' } }));
  await run(mw, req({ peer: MAILBOXD, headers: { [edge.TOKEN_HEADER]: 'tok-123' } }));
  await run(mw, req({ peer: MAILBOXD }));
  assert.equal(lookups, 0, 'loopback, token and basic ask no DNS');
  await Promise.all([1, 2, 3, 4, 5].map(() => run(mw, req({ peer: TRAEFIK, headers: { 'x-authentik-username': 'owner' } }))));
  assert.equal(lookups, edge.SSO_HOPS.length, 'five concurrent first requests share one refresh');
});

await t('a lookup that hangs is bounded, and a stale list answers while it refreshes', async () => {
  let clock = 0;
  let hang = false;
  const look = (name) => (hang ? new Promise(() => {}) : lookup(name));
  const mw = edge.middleware({ mode: 'enforce', deployment: 'staging', token: '', lookup: look,
    now: () => clock, timeoutMs: 300, log: { warn() {} } });
  const asOwner = req({ peer: TRAEFIK, headers: { 'x-authentik-username': 'owner' } });
  assert.equal((await run(mw, asOwner)).passed, true);
  clock += 61_000;
  hang = true;
  const started = Date.now();
  assert.equal((await run(mw, asOwner)).passed, true, 'the last list answers');
  assert.ok(Date.now() - started < 150, 'without waiting on the hanging refresh (its timeout is 300 ms)');
  const fresh = edge.hopsResolver({ deployment: 'staging', lookup: () => new Promise(() => {}), timeoutMs: 20 });
  assert.equal((await fresh()).size, 0, 'a first lookup that hangs ends at its timeout');
});

await t('a refresh that times out keeps the last answers; a real «not found» drops them', async () => {
  let clock = 0;
  let mode = 'ok';
  const look = (name) => (mode === 'hang' ? new Promise(() => {}) : mode === 'gone'
    ? Promise.reject(new Error('ENOTFOUND ' + name)) : lookup(name));
  const hops = edge.hopsResolver({ deployment: 'staging', lookup: look, now: () => clock, timeoutMs: 20 });
  assert.ok((await hops()).has(TRAEFIK));
  mode = 'hang'; clock += 61_000;
  await hops();                                              // stale: answers at once, refreshes behind
  await new Promise((r) => setTimeout(r, 40));               // the refresh times out
  clock += 1;
  assert.ok((await hops()).has(TRAEFIK), 'the last answers stay after a timeout');
  mode = 'gone'; clock += 61_000;
  await hops();
  await new Promise((r) => setTimeout(r, 10));
  clock += 1;
  assert.equal((await hops()).has(TRAEFIK), false, 'a real not-found drops them');
});

await t('auth.js sends edge trust through this check, and its Basic through basicChecker', async () => {
  const src = readFileSync(join(here, '..', 'src', 'api', 'middleware', 'auth.js'), 'utf8');
  const body = src.slice(src.indexOf('const isAuthenticated'), src.indexOf('if (req.session.authenticated)'));
  assert.match(body, /if \(EDGE_AUTH\) \{\s*return callerCheck\(req, res, next\);/);
  assert.doesNotMatch(body, /if \(EDGE_AUTH\) \{\s*return next\(\);/);
  assert.match(src, /basic: edgeCaller\.basicChecker\(\{ username: CONFIG\.AUTH_USERNAME, password: CONFIG\.AUTH_PASSWORD/);
});

await t('the READ token opens GET /api/accounts and GET /api/readyz, and nothing else', async () => {
  const { mw } = check('enforce');
  const H = { 'x-chat-office-token': 'read-456' };
  for (const path of ['/api/accounts', '/api/readyz']) {
    const r = await run(mw, req({ peer: MAILBOXD, path, headers: H }));
    assert.equal(r.passed, true, path);
  }
  // a write, another route, another spelling of the same route: refused, and the reason names what it opens
  for (const [method, path] of [['POST', '/api/accounts'], ['DELETE', '/api/accounts'], ['GET', '/api/subscribers'],
    ['POST', '/api/bot/broadcast'], ['GET', '/api/accounts/'], ['GET', '/API/accounts'], ['GET', '/api/readyz/x']]) {
    const r = await run(mw, req({ peer: MAILBOXD, method, path, headers: H }));
    assert.equal(r.passed, false, `${method} ${path}`);
    // refused: 401 + JSON under /api/, 403 + text elsewhere (`/API/…` is not under /api/)
    assert.equal(r.code, path.startsWith('/api/') ? 401 : 403, `${method} ${path}`);
    const why = r.code === 401 ? r.body.why : String(r.body);
    assert.match(why, /read token opens only GET \/api\/accounts and GET \/api\/readyz/, `${method} ${path}`);
  }
  // the route as Express mounts it: baseUrl + path
  const mounted = { ...req({ peer: MAILBOXD, path: '/accounts', headers: H }), baseUrl: '/api' };
  assert.equal((await run(mw, mounted)).passed, true);
});

await t('the read token is not the office token, and neither stands in for the other', async () => {
  const { mw } = check('enforce');
  // the office token still opens a write
  assert.equal((await run(mw, req({ peer: MAILBOXD, method: 'POST', path: '/api/bot/broadcast',
    headers: { 'x-chat-office-token': 'tok-123' } }))).passed, true);
  // an EMPTY read token (an office that never minted it) matches nothing, not even an empty header
  const empty = check('enforce', { readToken: '' }).mw;
  for (const h of [{}, { 'x-chat-office-token': '' }]) {
    assert.equal((await run(empty, req({ peer: MAILBOXD, path: '/api/accounts', headers: h }))).passed, false);
  }
  const pure = edge.decide({ peer: MAILBOXD, user: '', presented: 'read-456', hops: new Set(), token: 'tok-123',
    readToken: 'read-456', method: 'GET', path: '/api/accounts' });
  assert.deepEqual(pure, { ok: true, as: 'read' });
  assert.deepEqual([...edge.READ_ROUTES].sort(), ['/api/accounts', '/api/readyz']);
});

await t('auth.js hands the check CHAT_READ_TOKEN, and chat\'s compose passes it', async () => {
  const src = readFileSync(join(here, '..', 'src', 'api', 'middleware', 'auth.js'), 'utf8');
  assert.match(src, /readToken: process\.env\.CHAT_READ_TOKEN,/);
  const compose = readFileSync(join(here, '..', 'docker-compose.yml'), 'utf8');
  assert.match(compose, /^\s+- CHAT_READ_TOKEN=\$\{CHAT_READ_TOKEN:-\}$/m);
});

console.log(`${n} checks hold`);
