/**
 * The chat service's client of the platform's ONE credential plane, and of its own binding.
 *
 * WHAT CHANGED, AND WHY IT MATTERS. This file used to synthesise a local connection —
 * `chat_local-local`, plus one `chat_local-<userId>` per operator identity — that had no secret
 * anywhere and was answered from here rather than from the vault. That is what made selecting an
 * identity impersonation: there was no credential, so there was nothing to authenticate.
 *
 * Now a private profile is an ORDINARY INSTANCE (ai/context/app-engine-pattern.md §2): it is created
 * in the vault like any other, holds a minted API key as its secret, and is fetched from the vault
 * like any other. There is no synthetic instance and no local short-circuit in getSecret(). The
 * consequence is that `resolve()` stops special-casing private engines, and every one of the ~6
 * special cases that followed from the synthetic id is gone.
 *
 * What is deliberately kept:
 *   · status 0 ("unreachable") is a DIFFERENT answer from 404 ("gone"). Callers fall back to a cached
 *     credential on the first and must not on the second;
 *   · the BINDING lives on this app's own volume, so a connections outage degrades a LIST and does
 *     not un-select every app;
 *   · the binding is a {scope → instance} MAP from day one, with exactly one scope today
 *     ("deployment"). A later per-user scope must not need a second migration.
 */
const fs = require('fs');
const path = require('path');

const CONNECTIONS_URL = (process.env.CONNECTIONS_URL || 'http://connections:8990').replace(/\/+$/, '');

/** Where the binding lives. /data is the service's volume, so the selection survives a restart — an
 *  in-process variable would make the answer depend on which worker replied. */
const STATE_DIR = process.env.CHAT_STATE_DIR || '/data';
const BINDING_FILE = path.join(STATE_DIR, 'active.json');

const PROTOCOLS = ['chat_local', 'chat_wa_baileys', 'chat_tg_bot'];

/** The private engine. Profiles on it are real instances with real credentials — see the header. */
const LOCAL_PROTOCOL = 'chat_local';

/** One scope today. The MAP, not a scalar, is the whole point: when per-user selection arrives the
 *  key becomes the user id and nothing else moves. */
const DEPLOYMENT_SCOPE = 'deployment';

class ConnectionsError extends Error {
  constructor(message, status = 0) { super(message); this.name = 'ConnectionsError'; this.status = status; }
}

async function http(method, p, body) {
  let res;
  try {
    res = await fetch(`${CONNECTIONS_URL}${p}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(Number(process.env.CHAT_CONN_TIMEOUT_MS || 8000)),
    });
  } catch (e) {
    // Unreachable is NOT the same as refused: callers fall back to a cached credential on this,
    // and must not do so on a 404. Surfacing status 0 is how they tell the two apart.
    throw new ConnectionsError(`connections unreachable: ${e.message}`, 0);
  }
  if (res.status === 404) throw new ConnectionsError(`not found: ${p}`, 404);
  if (!res.ok) throw new ConnectionsError(`connections ${res.status} for ${p}`, res.status);
  return res.status === 204 ? {} : res.json();
}

// ── the binding ─────────────────────────────────────────────────────────────────────────────────

function readBindings() {
  try {
    const raw = JSON.parse(fs.readFileSync(BINDING_FILE, 'utf8'));
    return (raw && typeof raw.bindings === 'object' && raw.bindings) || {};
  } catch {
    return {};
  }
}

/** The bound instance for a scope, or null. A MISSING file means "nothing selected" — which
 *  resolveActive() reads as "the admin profile" — and is not an error. */
async function active(scope = DEPLOYMENT_SCOPE) {
  return readBindings()[scope] || null;
}

/** Persist the binding. `null` clears it (back to the implicit admin default).
 *  Written atomically: a half-written file reads as "nothing selected" on the next boot and would
 *  silently swap the operator's account back to the default. */
async function select(instanceId, scope = DEPLOYMENT_SCOPE) {
  const bindings = readBindings();
  if (instanceId) bindings[scope] = instanceId; else delete bindings[scope];
  await fs.promises.mkdir(STATE_DIR, { recursive: true }).catch(() => {});
  const tmp = `${BINDING_FILE}.tmp`;
  await fs.promises.writeFile(tmp, JSON.stringify({ version: 1, bindings }, null, 2), 'utf8');
  await fs.promises.rename(tmp, BINDING_FILE);
  return instanceId || null;
}

// ── the vault ───────────────────────────────────────────────────────────────────────────────────

/** The vault's raw instance list for one protocol glob. Throws on unreachable, so the caller can
 *  tell "no instances" from "no answer" — the reconciler must never delete on the second. */
async function rawInstances(protocol = null) {
  return http('GET', `/api/instances${protocol ? `?protocol=${encodeURIComponent(protocol)}` : ''}`);
}

/**
 * Every chat connection the console can offer.
 *
 * `localProfiles` is passed IN by server.js from the app's own database, and it is authoritative for
 * the private engine: this service OWNS those identities, so it can still list them (and still let
 * an operator switch between them) when the vault is unreachable. Vault rows for chat_local are
 * folded into them rather than added, so a profile appears exactly once.
 */
async function listInstances({ localProfiles = null } = {}) {
  const out = [];
  const seen = new Set();
  for (const p of localProfiles || []) {
    if (!p || !p.instance_id) continue;      // a profile whose instance is still deferred is not selectable yet
    seen.add(p.instance_id);
    out.push({
      id: p.instance_id,
      protocol: LOCAL_PROTOCOL,
      label: p.display_name || p.id,
      identity: p.is_admin ? `${p.id} · מנהל` : p.id,
      account_hint: p.id,
      profile_id: p.id,
      is_admin: Boolean(p.is_admin),
      builtin: false,
      status: p.status === 'active' ? 'ok' : p.status,
    });
  }
  try {
    const r = await rawInstances();
    for (const inst of r.instances || []) {
      if (!PROTOCOLS.includes(inst.protocol)) continue;
      if (seen.has(inst.id)) continue;       // already listed from our own profile table
      if (inst.protocol === LOCAL_PROTOCOL) continue;  // a vault row with no profile behind it is not an identity
      out.push(inst);
    }
    return { instances: out, reachable: true };
  } catch (e) {
    return { instances: out, reachable: false, error: e.message };
  }
}

/**
 * (protocol, secret) for one instance — from the vault, for EVERY protocol.
 *
 * The local short-circuit that used to live here is gone. A private profile holds a real credential
 * in the vault, so there is nothing left to synthesise and no branch for `resolve()` to take.
 */
async function getSecret(instanceId) {
  return http('GET', `/api/instances/${encodeURIComponent(instanceId)}/secret`);
}

async function createInstance(protocol, label, secret, accountHint) {
  return http('POST', '/api/instances', { protocol, label, secret, account_hint: accountHint });
}

/** Persist a secret this service just rotated, so the vault hands out the key we now accept. */
async function putSecret(instanceId, secret) {
  return http('PUT', `/api/instances/${encodeURIComponent(instanceId)}/secret`, { secret, replace: true });
}

async function deleteInstance(instanceId) {
  return http('DELETE', `/api/instances/${encodeURIComponent(instanceId)}`);
}

module.exports = {
  PROTOCOLS, LOCAL_PROTOCOL, DEPLOYMENT_SCOPE, ConnectionsError,
  active, select, listInstances, rawInstances, getSecret, createInstance, putSecret, deleteInstance,
};
