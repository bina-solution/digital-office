/**
 * WHO MAY REACH CHAT when the edge owns sign-in (TRUST_EDGE_AUTH=true) — issues/chat-lets-any-caller-in-….
 *
 * `isAuthenticated` used to call next() for every request under edge trust, reading nothing: measured on vps1
 * 2026-11-10, another container on traefik-network (mailboxd) got 200 from GET /api/subscribers with no identity
 * at all, and /api/bot/broadcast sits behind the same guard. A request is now believed in one of four ways:
 *
 *   sso       a PERSON: forward-auth's `X-authentik-username`, believed only when the TCP peer is one of the hops
 *             that write it — the console's own list (`_signin_hops`, platform-base/console/app.py): traefik (chat's
 *             own host), the console (its /a/chat/ proxy keeps the header only from traefik or the door) and the
 *             link's door (dgo-net / dgo-link: a linked office's mapped user). By container name
 *             `<hop>-<DEPLOYMENT_NAME>`, re-read once a minute, and only when such a header arrives.
 *   token     an office SERVICE: `X-Chat-Office-Token: <CHAT_API_TOKEN>`, compared in constant time. Not a Bearer:
 *             chat's engine reads every `Authorization: Bearer` as a LOCAL-chat profile key (chatapi/engine/auth.js).
 *             scripts/env-secrets.py mints CHAT_API_TOKEN per office (TABLE); a caller that holds it is stage two.
 *   basic     the office's chat credential as Basic auth on /api/, the rule this app keeps without edge trust — what
 *             the connections service sends today (platform-base/connections/app.py). auth.js refuses it while the
 *             password is the shipped fallback.
 *   loopback  this container itself (its healthcheck, `docker exec chat …`, the in-process test suites).
 *
 * The peer is the socket's, never `req.ip`: the app sets `trust proxy` in production, so `req.ip` is whatever
 * X-Forwarded-For a caller writes.
 *
 * STAGED (AGENTS.md non-negotiable 8). CHAT_CALLER_MODE=warn (the default until every office has run it) answers
 * an unproved caller as before and NAMES it in the log, once per method, route and peer per ten minutes, so the
 * list of callers that need a token is read off the offices, not guessed. CHAT_CALLER_MODE=enforce refuses it:
 * 401 on /api/, 403 elsewhere, with the reason. Not covered here: chatapi's routes that pass any key-shaped header
 * without reaching this check (issues/chat-opens-fifteen-routes-…).
 */
'use strict';

const crypto = require('crypto');
const dns = require('dns');

const SSO_HOPS = ['traefik', 'console', 'dgo-net', 'dgo-link'];
const TOKEN_HEADER = 'x-chat-office-token';
const LOOPBACK = new Set(['127.0.0.1', '::1']);
const WINDOW_MS = 10 * 60 * 1000;
const LOOKUP_TIMEOUT_MS = 2000;
const MODES = new Set(['warn', 'enforce']);

function peerOf(req) {
  const a = String((req.socket && req.socket.remoteAddress) || '');
  return a.startsWith('::ffff:') ? a.slice(7) : a;
}

function headerOf(req, name) {
  const v = (req.headers || {})[name];
  return String(Array.isArray(v) ? v[0] : v || '').trim();
}

function sameToken(given, want) {
  if (!given || !want) return false;
  const a = Buffer.from(given);
  const b = Buffer.from(want);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

/**
 * What the office's READ token opens, and nothing else: the two reads the office agent makes (apps/chat/operatives/
 * chat.accounts.md) — GET only, the exact paths (another spelling, a trailing slash, another case: refused). The office
 * token opens every route; this one is for a caller whose reads must not carry a credential that sends (the office
 * agent). Scope, not containment: bina-ds also holds the checkout's .env and the engine's socket, by design.
 */
const READ_ROUTES = new Set(['/api/accounts', '/api/readyz']);

/** Pure: what the facts of one request prove. `basic` is whether its Basic credential is the office's. */
function decide({ peer, user, presented, hops, token, basic = false, readToken = '', method = '', path = '' }) {
  if (LOOPBACK.has(peer)) return { ok: true, as: 'loopback' };
  if (user && hops.has(peer)) return { ok: true, as: 'sso' };
  if (sameToken(presented, token)) return { ok: true, as: 'token' };
  if (sameToken(presented, readToken)) {
    if (method === 'GET' && READ_ROUTES.has(path)) return { ok: true, as: 'read' };
    return { ok: false, why: `the office read token opens only GET ${[...READ_ROUTES].join(' and GET ')}, not ${method} ${path}` };
  }
  if (basic) return { ok: true, as: 'basic' };
  if (presented) return { ok: false, why: 'an office token that is not this office\'s chat token' };
  if (user) return { ok: false, why: `an identity header from ${peer || 'an unknown peer'}, which is not the edge` };
  return { ok: false, why: 'no identity: the request did not come through the edge and carries no service token' };
}

/** The values chat falls back to when CHAT_AUTH_PASS is unset (docker-compose.yml, src/config.js): no proof. */
const SHIPPED_FALLBACK_PASSWORDS = new Set(['', '1234']);

/**
 * `basic` for the middleware: the office's chat credential on /api/, as without edge trust — refused outright while
 * the password is a shipped fallback, which every office that never set one shares.
 */
function basicChecker({ username, password, parse }) {
  if (SHIPPED_FALLBACK_PASSWORDS.has(String(password || ''))) return () => false;
  return (req) => {
    if (!String(req.path || '').startsWith('/api/')) return false;
    const u = parse(req);
    return Boolean(u && u.name === username && u.pass === password);
  };
}

/**
 * The hops' addresses, by container name of this deployment; re-read after 60 s (15 s while empty). The names are
 * looked up together, each bounded by a timeout; one refresh is shared by every request that meets it, and while
 * it runs the last list answers (only the very first request waits).
 */
function hopsResolver({ deployment, lookup = dns.promises.lookup, now = Date.now, timeoutMs = LOOKUP_TIMEOUT_MS }) {
  const names = SSO_HOPS.map((h) => `${h}-${deployment || 'bina-deployment'}`);
  const TIMED_OUT = Symbol('timed out');
  let at = null;                              // null = never fetched (a clock can read 0)
  let addrs = new Set();
  const last = new Map();                     // name → the addresses of its last real answer
  let inflight = null;
  const bounded = (name) => new Promise((resolve) => {
    const timer = setTimeout(() => resolve(TIMED_OUT), timeoutMs);
    Promise.resolve().then(() => lookup(name, { all: true }))
      .then((rs) => { clearTimeout(timer); resolve(Array.isArray(rs) ? rs : []); },
        () => { clearTimeout(timer); resolve([]); });   // a hop that does not resolve proves nothing
  });
  const refresh = () => {
    if (!inflight) {
      inflight = Promise.all(names.map(async (name) => {
        const rs = await bounded(name);
        // a timeout keeps the name's last answer; only a real answer (or a real «not found») replaces it
        if (rs !== TIMED_OUT) last.set(name, rs.filter((r) => r && r.address).map((r) => r.address));
        return last.get(name) || [];
      })).then((lists) => {
        addrs = new Set(lists.flat());
        at = now();
        return addrs;
      }).finally(() => { inflight = null; });
    }
    return inflight;
  };
  return async function hops() {
    if (at !== null && now() - at < (addrs.size ? 60000 : 15000)) return addrs;
    if (at !== null) { refresh().catch(() => {}); return addrs; }   // stale: refresh behind, answer with the last list
    return refresh();
  };
}

function middleware({ mode, deployment, token, readToken = '', basic = () => false, log = console, lookup,
  now = Date.now, timeoutMs } = {}) {
  const said = String(mode || '').trim().toLowerCase();
  if (said && !MODES.has(said)) {
    log.warn(`chat-caller-mode: CHAT_CALLER_MODE=${JSON.stringify(String(mode))} is not warn or enforce — using warn`);
  }
  const enforce = said === 'enforce';
  const hops = hopsResolver({ deployment, lookup, now, timeoutMs });
  const named = new Map();
  return async function callerCheck(req, res, next) {
    let verdict;
    try {
      const peer = peerOf(req);
      const user = headerOf(req, 'x-authentik-username');
      const needHops = Boolean(user) && !LOOPBACK.has(peer);
      verdict = decide({ peer, user, presented: headerOf(req, TOKEN_HEADER),
        hops: needHops ? await hops() : new Set(), token, basic: Boolean(basic(req)), readToken,
        method: String(req.method || ''), path: String(req.baseUrl || '') + String(req.path || '') });
    } catch (e) {
      verdict = { ok: false, why: `the caller could not be checked (${e.message})` };
    }
    if (verdict.ok) return next();
    const path = String(req.path || req.url || '').split('?')[0];
    const route = (req.route && req.route.path) || path;
    const key = `${req.method} ${route} ${peerOf(req)}`;
    const t = now();
    if (!(t - (named.get(key) || 0) < WINDOW_MS)) {
      if (named.size > 2000) named.clear();
      named.set(key, t);
      log.warn(`chat-unproved-caller: ${req.method} ${JSON.stringify(path)} peer=${peerOf(req) || '?'} agent=${JSON.stringify(headerOf(req, 'user-agent').slice(0, 80))} — ${verdict.why}${enforce ? ' (refused)' : ' (let through: CHAT_CALLER_MODE=warn)'}`);
    }
    if (!enforce) return next();
    if (path.startsWith('/api/')) return res.status(401).json({ error: 'unproved caller', why: verdict.why });
    return res.status(403).send(`chat: ${verdict.why}`);
  };
}

module.exports = { basicChecker, decide, hopsResolver, middleware, peerOf, READ_ROUTES, SSO_HOPS, TOKEN_HEADER };
