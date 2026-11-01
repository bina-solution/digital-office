/**
 * PROFILES on the private chat engine — identity, credential, authorisation.
 *
 * This is the file that turns "pick who you want to be from a dropdown" into an authenticated act.
 * Before it, `chat_local-<userId>` was a synthesised connection id with no secret anywhere: anyone
 * who could open the app could name any identity and read that person's conversations. The UI said
 * so out loud, which was honest and still wrong.
 *
 * THE UNLOCK (ai/context/app-engine-pattern.md §2): every private profile is issued an API KEY at
 * creation. That key is its secret, stored in the connections vault exactly like an OAuth token, so
 * a private profile is a REAL instance and `resolve()` stops special-casing private engines. This
 * service keeps only the key's HASH — the vault keeps the key. Never both in one place: the vault is
 * where a client fetches a credential from, and a hash is all that is needed to verify one.
 *
 * THREE RINGS, checked here rather than in the UI:
 *   data   any active profile — every engine op, scoped to its own data BY THE SQL (see
 *          adapters/buzz.js, whose every query is scoped to this profile's own pubkey)
 *   self   any active profile — read/update itself, rotate its own key
 *   admin  is_admin only — create/edit/suspend/delete OTHER profiles
 *
 * And the invariant that keeps the system administrable: THE LAST ADMIN CANNOT BE DEMOTED, SUSPENDED
 * OR DELETED. Otherwise profile management becomes unreachable and the only way back is a psql
 * prompt, which is not a feature.
 *
 * Bootstrap (engine/bootstrap.js) is the one path exempt from profile auth, because it runs
 * IN-PROCESS with direct DB access rather than over the API. That is what resolves the
 * chicken-and-egg of needing an admin key in order to create the first admin.
 */
const crypto = require('crypto');

const defaultDb = require('../db');
const { mintIdentity } = require('../relay/identity');

const KEY_PREFIX = 'chatp_';
const ACTIVE = 'active';
const SUSPENDED = 'suspended';

/** A profile id is a slug: it becomes a vault account_hint, a `sender.id` a bot keys state on,
 *  and part of a URL.
 *  Deliberately the SAME pattern platform/schema/app.schema.json enforces on a declared profile, so
 *  a manifest that validates cannot be rejected here at boot. */
const ID_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

/**
 * Mint a credential.
 *
 * 32 bytes from the CSPRNG. The prefix is not decoration — it makes a leaked key greppable in a log
 * and tells whoever finds one what it opens, which is the difference between a secret that gets
 * rotated and one that sits in a paste bin because nobody recognised it.
 */
function mintKey() {
  return KEY_PREFIX + crypto.randomBytes(32).toString('hex');
}

/** The stored form. sha256 and not bcrypt on purpose: this is a 256-bit random token, not a
 *  password, so there is no dictionary to slow down and a fast hash is the right primitive. */
function hashKey(key) {
  return crypto.createHash('sha256').update(String(key || ''), 'utf8').digest('hex');
}

/** Colour for a profile's avatar — deterministic, so an identity keeps its colour across reloads.
 *  A NAME in the office's palette, not a value (the same list as relay/present.js). */
const PALETTE = ['sky-d', 'violet', 'lime-d', 'olive-d', 'plum-d', 'muted'].map(n => `var(--${n})`);
function colorOf(key) {
  let h = 0;
  for (const ch of String(key || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/**
 * The public shape. `key_hash` never leaves this module — a hash is not a secret, but publishing one
 * invites an offline search against a token nobody should be searching for.
 *
 * `key_fp` is a hash OF the hash, and it exists for exactly one reason: the adapter cache is keyed
 * on a credential fingerprint, so a rotation must change it or the old backend keeps serving. A
 * digest of a digest reveals nothing about the key and still changes the instant it rotates.
 */
function publicProfile(row) {
  if (!row) return null;
  return {
    id: row.id,
    display_name: row.display_name || row.id,
    is_admin: Boolean(row.is_admin),
    status: row.status || ACTIVE,
    instance_id: row.instance_id || null,
    // PUBLIC half only. The pubkey is not a secret — it is what every other participant on the
    // relay already sees — and the projection needs it to name a message's author.
    pubkey: row.pubkey || null,
    key_fp: row.key_hash
      ? crypto.createHash('sha256').update(`fp:${row.key_hash}`).digest('hex').slice(0, 16)
      : null,
    created_at: row.created_at || null,
  };
}

class ProfileError extends Error {
  constructor(message, status = 400) {
    super(message);
    this.name = 'ProfileError';
    this.status = status;
  }
}

class ProfileStore {
  constructor(opts = {}) {
    this.db = opts.db || defaultDb;
    this.schema = this.db.SCHEMA;
  }

  async _q(text, params) {
    await this.db.ensureSchema();
    return this.db.query(text, params);
  }

  // ── reads ─────────────────────────────────────────────────────────────────────────────────────

  async list() {
    const { rows } = await this._q(
      `SELECT id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at
         FROM ${this.schema}.chat_profiles
        ORDER BY is_admin DESC, created_at ASC, id ASC`);
    return rows.map(publicProfile);
  }

  async get(id) {
    const { rows } = await this._q(
      `SELECT id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at
         FROM ${this.schema}.chat_profiles WHERE id = $1`, [String(id || '')]);
    return publicProfile(rows[0]);
  }

  /**
   * credential → profile. THE authentication primitive.
   *
   * Looks up by HASH, never by any id the caller supplied, so a request cannot claim to be a profile
   * it does not hold the key for. The secret stored in the vault carries `profile_id` as a
   * convenience for clients; it is not consulted here, and that is deliberate — a field a caller can
   * edit must never be the thing that decides who they are.
   */
  async byKey(key) {
    const k = String(key || '').trim();
    if (!k) return null;
    const { rows } = await this._q(
      `SELECT id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at
         FROM ${this.schema}.chat_profiles WHERE key_hash = $1`, [hashKey(k)]);
    return publicProfile(rows[0]);
  }

  /** vault instance id → profile. How the connection bar's selection becomes an identity. */
  /** The profile that owns a relay pubkey, or null. The projection's hot path: it turns the author
   *  of an event into `sender.id = <profile slug>`, which is what every bot's per-user state keys
   *  on. A pubkey with no profile is a CONTACT, not an error — you can talk to someone who cannot
   *  act as an identity here. */
  async byPubkey(pubkey) {
    const pk = String(pubkey || '').trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(pk)) return null;
    const { rows } = await this._q(
      `SELECT id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at
         FROM ${this.schema}.chat_profiles WHERE pubkey = $1`, [pk]);
    return publicProfile(rows[0]);
  }

  /** Backfill a pubkey onto a profile that predates the relay engine. Refuses to OVERWRITE one:
   *  changing a profile's pubkey makes it a different person on the relay and detaches its whole
   *  history (relay/identity.js). Bootstrap is the only caller. */
  async setPubkey(id, pubkey) {
    const pk = String(pubkey || '').trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(pk)) throw new ProfileError('pubkey must be 64 hex characters', 400);
    const { rows } = await this._q(
      `UPDATE ${this.schema}.chat_profiles SET pubkey = $2
        WHERE id = $1 AND pubkey IS NULL
       RETURNING id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at`,
      [String(id || ''), pk]);
    if (!rows.length) {
      const existing = await this.get(id);
      if (existing && existing.pubkey) {
        throw new ProfileError(
          `profile ${id} already has a relay identity — replacing it would detach its history`, 409);
      }
      throw new ProfileError(`unknown profile ${id}`, 404);
    }
    return publicProfile(rows[0]);
  }

  /**
   * Replace a profile's relay identity, and say what that costs.
   *
   * ONLY for the one unrecoverable state: the vault no longer holds this profile's nsec, so it can
   * no longer sign as its pubkey — that identity is already dead, and the profile is unusable until
   * it has another. Minting a new one is the recovery, not the damage.
   *
   * What it costs, stated because the caller must log it: everything the old pubkey signed stays
   * under the old pubkey. Its messages remain in the channels (other people still see them) but the
   * profile no longer OWNS them, and its channel memberships and read state are gone with it. There
   * is no un-reset. Never call this to "refresh" a credential — that is `rotate()`.
   */
  async resetIdentity(id) {
    const { mintIdentity } = require('../relay/identity');
    const { nsec, pubkey } = mintIdentity();
    const { rows } = await this._q(
      `UPDATE ${this.schema}.chat_profiles SET pubkey = $2 WHERE id = $1
       RETURNING id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at`,
      [String(id || ''), pubkey]);
    if (!rows.length) throw new ProfileError(`unknown profile ${id}`, 404);
    return { profile: publicProfile(rows[0]), nsec, pubkey };
  }

  async byInstance(instanceId) {
    const id = String(instanceId || '').trim();
    if (!id) return null;
    const { rows } = await this._q(
      `SELECT id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at
         FROM ${this.schema}.chat_profiles WHERE instance_id = $1`, [id]);
    return publicProfile(rows[0]);
  }

  /** The profile a request falls back to when nothing is bound: the first admin, oldest first. */
  async firstAdmin() {
    const { rows } = await this._q(
      `SELECT id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at
         FROM ${this.schema}.chat_profiles
        WHERE is_admin = true AND status = '${ACTIVE}'
        ORDER BY created_at ASC, id ASC LIMIT 1`);
    return publicProfile(rows[0]);
  }

  async adminCount() {
    const { rows } = await this._q(
      `SELECT count(*)::int AS n FROM ${this.schema}.chat_profiles
        WHERE is_admin = true AND status = '${ACTIVE}'`);
    return rows[0] ? rows[0].n : 0;
  }

  /** Would removing/demoting/suspending this profile leave the deployment with no way in? */
  async isLastAdmin(id) {
    const p = await this.get(id);
    if (!p || !p.is_admin || p.status !== ACTIVE) return false;
    return (await this.adminCount()) <= 1;
  }

  // ── writes ────────────────────────────────────────────────────────────────────────────────────

  /**
   * Create a profile: its row, its credential and its relay identity, in one operation.
   *
   * There is no longer a second `chat_users` row to write. A profile used to be a person row too,
   * because conversations lived in this database and had a foreign key to it. They live on the
   * relay now, where a person IS a pubkey — so the identity is the `pubkey` column, and the NAME
   * other participants see is a kind:0 event the caller publishes with the nsec it is handed back
   * (engine/bootstrap.js does this the moment it creates the vault instance).
   *
   * Returns the key IN CLEAR, exactly once. There is no second chance to read it and there must not
   * be — the caller (bootstrap, or the admin route) is responsible for putting it in the vault. If
   * it is lost, the answer is a rotation, not a lookup.
   */
  async create({ id, display_name: displayName, is_admin: isAdmin = false, color = null } = {}) {
    const pid = String(id || '').trim().toLowerCase();
    if (!ID_RE.test(pid)) {
      throw new ProfileError('a profile id may contain lowercase letters, digits, dot, dash and underscore', 400);
    }
    const name = String(displayName || '').trim() || pid;
    const key = mintKey();
    // Minted HERE, in the same operation as the row, for the same reason the api key is (§7:
    // creating a profile creates its connection). The nsec goes to the vault with the key; this
    // table keeps only the pubkey. See relay/identity.js for why these two rotate differently.
    const { nsec, pubkey } = mintIdentity();
    const S = this.schema;
    await this.db.ensureSchema();
    const created = await this.db.tx(async (c) => {
      const { rows } = await c.query(
        `INSERT INTO ${S}.chat_profiles (id, display_name, is_admin, key_hash, status, pubkey)
         VALUES ($1, $2, $3, $4, '${ACTIVE}', $5)
         ON CONFLICT (id) DO NOTHING
         RETURNING id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at`,
        [pid, name, Boolean(isAdmin), hashKey(key), pubkey]);
      return rows[0] || null;
    });
    if (!created) throw new ProfileError(`a profile with id "${pid}" already exists`, 409);
    // `nsec` is returned ONCE, to the caller that will store it in the vault, and is never readable
    // from this service again — the same contract as `key`.
    return { profile: publicProfile(created), key, nsec };
  }

  /** Record the vault instance minted for a profile. Separate from create() because the vault may
   *  be unreachable at that moment, and a profile without its instance yet is a RETRY. */
  async setInstance(id, instanceId) {
    const { rows } = await this._q(
      `UPDATE ${this.schema}.chat_profiles SET instance_id = $2 WHERE id = $1
       RETURNING id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at`,
      [String(id || ''), instanceId || null]);
    return publicProfile(rows[0]);
  }

  /**
   * Rotate a profile's key. The OLD key stops working the moment this commits, which is the point.
   *
   * The caller must write the new key to the vault; until it does, clients holding the old one are
   * locked out. That ordering is deliberate — the alternative (vault first) leaves a window where the
   * vault hands out a key this service does not yet accept, and a client cannot tell that apart from
   * a broken credential.
   */
  async rotate(id) {
    const key = mintKey();
    const { rows } = await this._q(
      `UPDATE ${this.schema}.chat_profiles SET key_hash = $2 WHERE id = $1
       RETURNING id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at`,
      [String(id || ''), hashKey(key)]);
    if (!rows.length) throw new ProfileError(`unknown profile ${id}`, 404);
    return { profile: publicProfile(rows[0]), key };
  }

  /**
   * Update a profile's name, admin flag or status.
   *
   * The last-admin guard lives HERE and not in the route, because there are three routes that can
   * reach it (patch, delete, suspend) and a guard that has to be remembered three times is a guard
   * that will be forgotten once.
   */
  async update(id, { display_name: displayName, is_admin: isAdmin, status } = {}) {
    const pid = String(id || '').trim();
    const current = await this.get(pid);
    if (!current) throw new ProfileError(`unknown profile ${pid}`, 404);

    const losesAdmin = isAdmin === false && current.is_admin;
    const losesActive = status === SUSPENDED && current.status === ACTIVE && current.is_admin;
    if ((losesAdmin || losesActive) && await this.isLastAdmin(pid)) {
      throw new ProfileError('this is the last admin profile — demoting or suspending it would leave nobody able to manage profiles', 409);
    }
    if (status !== undefined && status !== ACTIVE && status !== SUSPENDED) {
      throw new ProfileError(`status must be "${ACTIVE}" or "${SUSPENDED}"`, 400);
    }

    const S = this.schema;
    const sets = [];
    const args = [pid];
    if (displayName !== undefined) { args.push(String(displayName || '').trim() || pid); sets.push(`display_name = $${args.length}`); }
    if (isAdmin !== undefined) { args.push(Boolean(isAdmin)); sets.push(`is_admin = $${args.length}`); }
    if (status !== undefined) { args.push(status); sets.push(`status = $${args.length}`); }
    if (!sets.length) return current;

    await this.db.ensureSchema();
    const out = await this.db.tx(async (c) => {
      const { rows } = await c.query(
        `UPDATE ${S}.chat_profiles SET ${sets.join(', ')} WHERE id = $1
         RETURNING id, display_name, is_admin, key_hash, status, instance_id, pubkey, created_at`, args);
      // A rename used to have to be written twice — here and on the person row the conversation
      // list rendered from — or the switcher showed the new name and every chat header the old one.
      // The name other participants see is a kind:0 event on the relay now, so the second write is
      // a PUBLISH rather than an UPDATE, and it belongs to whoever holds the nsec. engine/routes.js
      // refreshes it through the resolved backend after this returns; a failure there costs the
      // relay-side display name until the next reconcile, never the rename itself.
      return rows[0];
    });
    return publicProfile(out);
  }

  /**
   * Delete a profile — REMOVES ACCESS, NEVER DATA.
   *
   * Every message that identity signed and every channel it belongs to stay exactly where they are,
   * on the relay, under its pubkey. Removing a login must not remove a company's history — that is
   * not what "remove this login" means anywhere else and must not mean it here. (It also could not:
   * the relay's log is append-only and signed by a key this service does not keep.)
   */
  async remove(id) {
    const pid = String(id || '').trim();
    const current = await this.get(pid);
    if (!current) throw new ProfileError(`unknown profile ${pid}`, 404);
    if (await this.isLastAdmin(pid)) {
      throw new ProfileError('this is the last admin profile — removing it would leave nobody able to manage profiles', 409);
    }
    await this._q(`DELETE FROM ${this.schema}.chat_profiles WHERE id = $1`, [pid]);
    return { ok: true, id: pid, instance_id: current.instance_id || null };
  }
}

module.exports = {
  ProfileStore, ProfileError,
  mintKey, hashKey, publicProfile, colorOf,
  KEY_PREFIX, ID_RE, ACTIVE, SUSPENDED,
};
