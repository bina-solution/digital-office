/**
 * The local chat backend's connection to the platform database.
 *
 * WHICH database: the one the platform already runs — `platform-base/postgres`, reachable on the
 * traefik network under the alias `supabase-db` (that alias is the address every DATABASE_URL in
 * this stack already holds; see the header of platform-base/postgres/docker-compose.yml). No new
 * service is introduced for chat, which is the whole point of stage 3.
 *
 * WHY a direct connection and not indox's PostgREST transport: indox reaches the same database
 * through kong/PostgREST, and that works because indox stores flat rows and filters them. The chat
 * list is one query with three LATERALs — newest message, unread count, peer — and PostgREST cannot
 * express it, so it would become N+1 HTTP calls per conversation. It is also the wrong dependency:
 * kong/PostgREST belong to the OPTIONAL gallery app `apps/supabase`, while the database is layer 1
 * and always present. So this follows the other direct-DB consumer in the repo instead
 * (apps/supabase's storage service: `postgres://…@supabase-db:5432/…`), and reads the same env
 * names the platform already mints — SUPABASE_DB_PASSWORD / SUPABASE_DB_NAME.
 *
 * EVERYTHING HERE DEGRADES. `pg` is required lazily and a missing driver is treated exactly like an
 * unreachable server, so the pure projection functions in relay/present.js stay importable (and
 * unit-testable) with no driver installed, and a database outage produces an empty conversation
 * list rather than a 500 — the contract indox's /sync/registry established.
 */
const fs = require('fs');
const path = require('path');

/** Postgres identifiers are not parameterisable, so the schema name is validated, not escaped. */
function safeSchema(name) {
  const s = String(name || 'public').trim();
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(s)) throw new Error(`invalid CHAT_DB_SCHEMA: ${name}`);
  return s;
}

const SCHEMA = safeSchema(process.env.CHAT_DB_SCHEMA || 'public');

// There is NO process-wide identity any more. `CHAT_SELF_USER` used to seed one here and every
// backend defaulted to it, which made "who am I" a property of the container rather than of the
// request. Identities are now rows in chat_profiles, declared in app.json and reconciled at start by
// chatapi/engine/bootstrap.js, and each carries a credential. See ai/context/app-engine-pattern.md §2.

/**
 * The connection string.
 *
 * CHAT_DATABASE_URL wins so a deployment can point chat at somewhere else entirely; DATABASE_URL is
 * the stack-wide spelling; otherwise it is assembled from the platform's own env names, which is
 * what makes this work with no compose change on a machine where SUPABASE_DB_PASSWORD is already in
 * the environment.
 */
function connectionString() {
  if (process.env.CHAT_DATABASE_URL) return process.env.CHAT_DATABASE_URL;
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL;
  const host = process.env.CHAT_DB_HOST || 'supabase-db';
  const port = process.env.CHAT_DB_PORT || '5432';
  const user = process.env.CHAT_DB_USER || 'postgres';
  const pass = process.env.CHAT_DB_PASSWORD || process.env.SUPABASE_DB_PASSWORD || '';
  const name = process.env.CHAT_DB_NAME || process.env.SUPABASE_DB_NAME || 'postgres';
  return `postgres://${encodeURIComponent(user)}:${encodeURIComponent(pass)}@${host}:${port}/${name}`;
}

/** Host/database only — safe to put in a probe response, unlike the connection string. */
function describe() {
  try {
    const u = new URL(connectionString());
    return { host: u.hostname, port: u.port || '5432', database: u.pathname.replace(/^\//, ''), schema: SCHEMA };
  } catch {
    return { host: '?', port: '?', database: '?', schema: SCHEMA };
  }
}

let _pool = null;
let _pgMissing = null;

/**
 * The pool, created on first use.
 *
 * The timeouts are the load-bearing part. Without connectionTimeoutMillis a database that is DOWN
 * (as opposed to refusing) leaves every request hanging until the client gives up, which turns a
 * degraded backend into a hung one — and the health probe would hang with it. The `error` listener
 * matters just as much: node-postgres emits `error` on IDLE clients when the server restarts, and
 * an unhandled `error` event takes the whole process down. Chat would then crash for a database
 * blip it is supposed to survive.
 */
function pool() {
  if (_pool) return _pool;
  if (_pgMissing) throw _pgMissing;
  let pg;
  try {
    // eslint-disable-next-line global-require
    pg = require('pg');
  } catch (e) {
    _pgMissing = new Error(`the 'pg' driver is not installed: ${e.message}`);
    throw _pgMissing;
  }
  _pool = new pg.Pool({
    connectionString: connectionString(),
    max: Number(process.env.CHAT_DB_POOL_MAX || 5),
    connectionTimeoutMillis: Number(process.env.CHAT_DB_CONNECT_TIMEOUT_MS || 4000),
    idleTimeoutMillis: 30000,
    query_timeout: Number(process.env.CHAT_DB_QUERY_TIMEOUT_MS || 8000),
    statement_timeout: Number(process.env.CHAT_DB_QUERY_TIMEOUT_MS || 8000),
  });
  _pool.on('error', (err) => {
    console.error('[chat/db] idle client error (pool survives):', err.message);
  });
  return _pool;
}

async function query(text, params) {
  return pool().query(text, params);
}

/** Run several statements on ONE connection inside a transaction. */
async function tx(fn) {
  const client = await pool().connect();
  try {
    await client.query('BEGIN');
    const out = await fn(client);
    await client.query('COMMIT');
    return out;
  } catch (e) {
    try { await client.query('ROLLBACK'); } catch { /* the connection is already gone */ }
    throw e;
  } finally {
    client.release();
  }
}

let _ensured = null;

/**
 * Create the schema if it is not there — idempotent, and run on the first op rather than only at
 * boot, so a database that comes up AFTER the app still gets provisioned without a restart.
 *
 * The memo holds the PROMISE, so twenty concurrent first requests provision once. On failure the
 * memo is cleared, because a cached rejection would make one unlucky start permanent.
 */
function ensureSchema() {
  if (_ensured) return _ensured;
  _ensured = (async () => {
    const ddl = fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf8')
      .split('__SCHEMA__').join(SCHEMA);
    if (SCHEMA !== 'public') await query(`CREATE SCHEMA IF NOT EXISTS ${SCHEMA}`);
    await query(ddl);
    return true;
  })().catch((e) => { _ensured = null; throw e; });
  return _ensured;
}

/**
 * Listen for the schema's NOTIFY channel and call `onEvent(payload)` for each notification.
 *
 * A DEDICATED client, deliberately NOT one from the pool. A pooled client is released back after
 * the query and may be handed to someone else or closed by `idleTimeoutMillis: 30000` — either way
 * the LISTEN registration goes with it and notifications stop arriving, with nothing to show for it
 * because a listener that hears nothing looks exactly like a quiet chat.
 *
 * Reconnects with backoff, because the whole point of the platform's degrade-don't-crash contract is
 * that a database restart is survivable: on `error` or `end`, wait and re-LISTEN. Callers therefore
 * never see a dead subscription, only a gap.
 *
 * @returns {Promise<function(): Promise<void>>} stop — unsubscribes and closes the client.
 */
async function listen(channel, onEvent) {
  if (_pgMissing) throw _pgMissing;
  let pg;
  try {
    // eslint-disable-next-line global-require
    pg = require('pg');
  } catch (e) {
    _pgMissing = new Error(`the 'pg' driver is not installed: ${e.message}`);
    throw _pgMissing;
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(String(channel))) throw new Error(`invalid channel: ${channel}`);

  let client = null;
  let stopped = false;
  let delay = 500;

  const connect = async () => {
    if (stopped) return;
    client = new pg.Client({ connectionString: connectionString() });
    // Attached BEFORE connect: node-postgres emits `error` on a client whose server went away, and
    // an unhandled `error` event ends the process — chat would die for the blip it should survive.
    client.on('error', (e) => {
      console.error('[chat/db] listener client error:', e.message);
      retry();
    });
    client.on('end', retry);
    client.on('notification', (msg) => {
      if (msg.channel !== channel) return;
      let payload = null;
      try { payload = JSON.parse(msg.payload); } catch { payload = { raw: msg.payload }; }
      try { onEvent(payload); } catch (e) { console.error('[chat/db] listener callback threw:', e.message); }
    });
    await client.connect();
    await client.query(`LISTEN ${channel}`);
    delay = 500;   // a successful attach resets the backoff
  };

  function retry() {
    if (stopped) return;
    const c = client;
    client = null;
    if (c) { c.removeAllListeners(); c.end().catch(() => {}); }
    setTimeout(() => {
      connect().catch((e) => { console.error('[chat/db] listener reconnect failed:', e.message); retry(); });
    }, delay).unref?.();
    delay = Math.min(delay * 2, 30000);
  }

  await connect();
  return async function stop() {
    stopped = true;
    const c = client;
    client = null;
    if (c) { c.removeAllListeners(); try { await c.end(); } catch { /* already gone */ } }
  };
}

async function close() {
  const p = _pool;
  _pool = null;
  _ensured = null;
  if (p) await p.end();
}

/** Test seam: forget the memoised pool/schema state without touching a live server. */
function _reset() { _pool = null; _ensured = null; _pgMissing = null; }

module.exports = {
  SCHEMA,
  connectionString, describe, query, tx, ensureSchema, listen, close, safeSchema, _reset,
};
