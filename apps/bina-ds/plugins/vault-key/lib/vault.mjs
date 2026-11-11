/**
 * vault.mjs — the office's credential plane (`connections`) as a LIVE credential source.
 *
 * WHAT PROBLEM THIS SOLVES. The office keeps its keys in one place — the `connections` app — and
 * every app that needs one declares it in its own `app.json` and receives it as an environment
 * variable at boot (`platform-base/connections/inject.sh`). That is a snapshot: a key that changes
 * in the vault reaches the app only at the next restart, and a key the operator types into the
 * harness's Models page is a copy that lives on the harness volume instead of the vault.
 *
 * This module is the per-request half of that plane. A credential reference whose stored value is
 * `vault:<connection-id>` is not a key at all — it is a POINTER to a connection — and the value
 * behind it is fetched here, at the moment it is used, through the broker (`POST /api/broker/lease`)
 * with this container's own identity. Nothing is written back: the key lives in the vault's memory
 * and in this process's short cache, never in `.credentials.yaml`.
 *
 * THE DOOR IS THE BROKER, NOT A SHORTCUT. `/api/reveal/<cid>` would return any secret to anything on
 * the office network; the broker is the one route that (a) names the caller as a compose service,
 * (b) grants only the connections THAT SERVICE declares in app.json, and (c) audits every grant.
 * The container-id header is the second factor the broker's `identity.py` documents, read here the
 * same way `inject.sh` reads it: out of `/proc/self/mountinfo`, where docker bind-mounts it.
 *
 * WHAT IT DOES NOT DO. It never caches a value for longer than `cacheSeconds`, and it never serves a
 * stale value after a failed lease — a vault that cannot be reached makes the credential UNRESOLVED
 * (and the reason is logged), which is the safe direction: an app must not talk to a provider with a
 * key nobody can vouch for.
 */

import fs from 'node:fs'

/** The prefix that turns a stored credential value into a pointer at one vault connection. */
export const VAULT_PREFIX = 'vault:'

/** A connection id, as the vault spells them (`deepseek-key`, `n8n-postgres`). */
const CONNECTION_ID = /^[a-z0-9][a-z0-9-]*$/

/**
 * The connection a stored credential value points at.
 * @param value - the value stored for a credential reference.
 * @returns the connection id, or `undefined` when the value is a literal secret (or malformed).
 */
export function vaultConnectionOf(value) {
  if (typeof value !== 'string' || !value.startsWith(VAULT_PREFIX)) return undefined
  const cid = value.slice(VAULT_PREFIX.length).trim()
  return CONNECTION_ID.test(cid) ? cid : undefined
}

/**
 * The value an operator's pick stores for one connection — the whole of the binding.
 * @param connection - a vault connection id.
 * @returns the credential value to store under the reference.
 */
export function vaultBindingFor(connection) {
  if (typeof connection !== 'string' || !CONNECTION_ID.test(connection)) {
    throw new TypeError(`not a vault connection id: ${String(connection)}`)
  }
  return `${VAULT_PREFIX}${connection}`
}

/**
 * This container's own docker id — the broker's container-id factor.
 *
 * Docker bind-mounts `/var/lib/docker/containers/<64-hex>/{hostname,hosts,resolv.conf}` into every
 * container, so the id is legible from inside with no engine access. `inject.sh` reads it the same
 * way (mountinfo first, cgroup second); this is the same scan in JavaScript.
 * @returns the 64-character id, or `''` when it cannot be found.
 */
export function selfContainerId() {
  for (const [path, marker] of [['/proc/self/mountinfo', '/containers/'], ['/proc/self/cgroup', '/docker/']]) {
    let text
    try {
      text = fs.readFileSync(path, 'utf8')
    } catch {
      continue
    }
    let at = text.indexOf(marker)
    while (at !== -1) {
      const candidate = text.slice(at + marker.length, at + marker.length + 64)
      if (/^[0-9a-f]{64}$/.test(candidate)) return candidate
      at = text.indexOf(marker, at + 1)
    }
  }
  return ''
}

/**
 * The markers `.env.ex` ships as fill-me-in values, copied verbatim from the vault's own rule
 * (`platform-base/connections/app.py`, `_PLACEHOLDER_MARKERS`): the vault reports such a connection
 * as «לא מוגדר», so a lease that returns one must not read to us as a key either. Two ideas of
 * "configured" that disagree is the bug this list prevents.
 */
const PLACEHOLDER_MARKERS = [
  'your-', 'your_', 'change_me', 'changeme', 'example.com', '<', 'todo',
  'placeholder', 'xxx', 'fill-me', 'fillme', 'replace_me', 'replace-me',
  // The fabricated stand-in older builds minted into derived fields; never configured again.
  'derived:',
]

/**
 * Whether a value is a fill-me-in marker rather than a secret.
 * @param value - a value the vault returned.
 * @returns true when it must not be used as a key.
 */
export function isPlaceholder(value) {
  const low = String(value).trim().toLowerCase()
  return PLACEHOLDER_MARKERS.some((marker) => low.includes(marker))
}

/**
 * Pick the value a reference asks for out of one connection's leased environment.
 *
 * The broker answers the lease with the connection's OWN environment names (`DEEPSEEK_API_KEY` for
 * `deepseek-key`), so the reference names its value directly. The single-value fallback covers a
 * connection whose primary field is spelled differently from the reference that points at it.
 * @param env - the `env` map of one lease.
 * @param ref - the credential reference being resolved.
 * @returns the value, or `undefined` when the connection holds nothing usable.
 */
export function secretFrom(env, ref) {
  if (env === null || typeof env !== 'object') return undefined
  const named = env[ref]
  if (typeof named === 'string' && named.length > 0 && !isPlaceholder(named)) return named
  const values = Object.values(env).filter(
    (value) => typeof value === 'string' && value.length > 0 && !isPlaceholder(value),
  )
  return values.length === 1 ? values[0] : undefined
}

/**
 * A lease answer, normalised.
 * @typedef {{ok: true, env: Record<string, string>} | {ok: false, reason: string}} Lease
 */

/**
 * The vault, as a cached per-request source.
 *
 * One cache entry per connection, `cacheSeconds` long, dropped on the first failed lease: a value
 * the vault has just refused must not keep being served from memory.
 */
export class VaultSource {
  /**
   * @param {object} options - how to reach the vault and how long to remember an answer.
   * @param {string} options.url - the connections app's base URL (`http://connections:8990`).
   * @param {string} options.service - this app's compose service, the broker's cross-check.
   * @param {number} [options.cacheSeconds] - how long one connection's lease is reused.
   * @param {number} [options.timeoutMs] - one lease's whole timeout.
   * @param {(message: string, error?: unknown) => void} [options.log] - a warning sink.
   */
  constructor({ url, service, cacheSeconds = 30, timeoutMs = 4000, log }) {
    this.url = String(url || 'http://connections:8990').replace(/\/+$/, '')
    this.service = service
    this.ttlMs = Math.max(0, cacheSeconds) * 1000
    this.timeoutMs = timeoutMs
    this.log = log ?? (() => {})
    /** @type {Map<string, {at: number, lease: Lease}>} */
    this.cache = new Map()
    /** @type {Map<string, Promise<Lease>>} */
    this.inflight = new Map()
  }

  /**
   * The secret behind one connection, for one reference.
   * @param {string} ref - the credential reference asking (audit and env lookup).
   * @param {string} connection - the vault connection id.
   * @returns {Promise<string | undefined>} the value, or `undefined` when the vault holds none.
   * @throws {Error} when the vault could not be asked at all — the caller must fail loudly.
   */
  async secret(ref, connection) {
    const lease = await this.lease(connection)
    if (!lease.ok) throw new Error(`vault: ${connection} could not be read — ${lease.reason}`)
    return secretFrom(lease.env, ref)
  }

  /**
   * Whether one connection currently holds a value, without ever moving the value out of here.
   * @param {string} connection - the vault connection id.
   * @returns {Promise<{configured: boolean, reason?: string}>} the state, never a value.
   */
  async state(connection) {
    const lease = await this.lease(connection)
    if (!lease.ok) return { configured: false, reason: lease.reason }
    const values = Object.values(lease.env ?? {}).filter(
      (value) => typeof value === 'string' && value.length > 0 && !isPlaceholder(value),
    )
    return { configured: values.length > 0 }
  }

  /**
   * One connection's leased environment, cached — the raw answer, failure and all.
   * @param {string} connection - the vault connection id.
   * @returns {Promise<Lease>} the normalised answer.
   */
  async lease(connection) {
    const now = Date.now()
    const hit = this.cache.get(connection)
    if (hit !== undefined && now - hit.at < this.ttlMs) return hit.lease
    const running = this.inflight.get(connection)
    if (running !== undefined) return running
    const attempt = this.fetchLease(connection)
      .then((lease) => {
        this.cache.set(connection, { at: Date.now(), lease })
        return lease
      })
      .finally(() => this.inflight.delete(connection))
    this.inflight.set(connection, attempt)
    return attempt
  }

  /**
   * Ask the broker for one connection. Narrow by construction: the body names one id, and the broker
   * intersects it with what this service declares.
   * @param {string} connection - the vault connection id.
   * @returns {Promise<Lease>} the normalised answer.
   */
  async fetchLease(connection) {
    const headers = { 'content-type': 'application/json' }
    const containerId = selfContainerId()
    if (containerId !== '') headers['x-conn-container'] = containerId
    let response
    try {
      response = await fetch(`${this.url}/api/broker/lease`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ service: this.service, connections: [connection] }),
        signal: AbortSignal.timeout(this.timeoutMs),
      })
    } catch (error) {
      const reason = `the connections app did not answer at ${this.url} (${
        error instanceof Error ? error.message : String(error)
      })`
      this.log(`vault: ${reason}`)
      return { ok: false, reason }
    }
    let body
    try {
      body = await response.json()
    } catch {
      body = undefined
    }
    if (!response.ok) {
      const reason = `${this.url} refused the lease for ${connection} (HTTP ${response.status}): ${
        (body && (body.error || body.reason)) || 'no reason given'
      }`
      this.log(`vault: ${reason}`)
      return { ok: false, reason }
    }
    const refused = Array.isArray(body?.refused) ? body.refused : []
    if (refused.length > 0) {
      const reason = refused.map((row) => row?.reason || `${row?.id} refused`).join('; ')
      this.log(`vault: ${connection} is not granted to ${this.service} — ${reason}`)
      return { ok: false, reason }
    }
    const env = body?.env && typeof body.env === 'object' ? body.env : {}
    return { ok: true, env }
  }
}
