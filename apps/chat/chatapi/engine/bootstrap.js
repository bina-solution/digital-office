/**
 * BOOTSTRAP RECONCILER — the declared profiles in app.json become real, credentialed identities.
 *
 * Runs at app start, IN-PROCESS, with direct database access. That is not a shortcut: it is the one
 * path exempt from profile authentication, and being in-process is what makes the exemption safe —
 * it never listens on a socket, so there is no unauthenticated route to reach it through. It is also
 * the only thing that can resolve the chicken-and-egg the contract otherwise creates: managing
 * profiles requires an admin key, and an admin key can only come from a profile someone created.
 *
 * IDEMPOTENT, and the idempotence is the whole feature. `bbox run` is run repeatedly against live
 * deployments, so every state below has to converge to the same place:
 *
 *   declared, profile missing        → create the row, mint a key, store the hash, create the vault
 *                                      instance, record it in the ledger
 *   declared, profile + instance ok  → LEAVE ALONE. Never re-mint. A re-minted key silently breaks
 *                                      every client that already stored one, and nothing errors
 *   declared, profile ok, no instance→ re-create the instance from the key held in the ledger; if
 *                                      that key is gone, rotate and say so in the log
 *   ours, no longer declared         → remove the profile and its instance
 *   exists but never ours            → LEAVE ALONE. A redeploy must never delete an operator's
 *                                      hand-made profile
 *   connections unreachable          → keep the profile, retry the instance on a later pass, never
 *                                      fail the boot, and NEVER mint a second key
 *
 * THE LEDGER is the set of profiles this reconciler created, on the app's own volume
 * (CHAT_STATE_DIR). It is what distinguishes "we made this, so we may remove it" from "an operator
 * made this, so hands off" — without it, un-declaring a profile and deleting someone's work look
 * identical. It also holds the whole SECRET of any profile whose vault instance has not been
 * created yet, which is what makes "never mint twice" survivable across a restart while
 * connections is down. That secret is both halves of the identity — the api key AND the relay
 * nsec — because only the first of those can be re-issued: a re-minted nsec is not a refreshed
 * credential, it is a different person on the relay (see relay/identity.js).
 */
const fs = require('fs');
const path = require('path');

const cc = require('../connections_client');
const { ProfileStore } = require('./profiles');

const STATE_DIR = process.env.CHAT_STATE_DIR || '/data';
const LEDGER_FILE = path.join(STATE_DIR, 'engine-profiles.json');

/** app.json ships in the image (`COPY . .` with WORKDIR /app), and this file sits at
 *  /app/chatapi/engine/, so the manifest is two directories up. Same path in the repo. */
const APP_JSON = process.env.CHAT_APP_MANIFEST || path.join(__dirname, '..', '..', 'app.json');

/** The declared profiles, or [] — a manifest we cannot read must not stop the service from booting.
 *  It costs the declared identities, not the chat. */
function declaredProfiles(file = APP_JSON) {
  try {
    const manifest = JSON.parse(fs.readFileSync(file, 'utf8'));
    const engine = manifest && manifest.engine;
    if (!engine || engine.id !== cc.LOCAL_PROTOCOL) return [];
    return (engine.profiles || []).filter((p) => p && p.id).map((p) => ({
      id: String(p.id).trim().toLowerCase(),
      display_name: String(p.display_name || p.id),
      admin: Boolean(p.admin),
    }));
  } catch (e) {
    console.error('[chat/engine] cannot read declared profiles:', e.message);
    return [];
  }
}

function readLedger(file = LEDGER_FILE) {
  try {
    const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
    return { version: 1, profiles: (raw && raw.profiles) || {} };
  } catch {
    return { version: 1, profiles: {} };
  }
}

/** Atomic: a half-written ledger reads as "we created nothing", and the next pass would then treat
 *  every profile as an operator's and never reconcile them again. */
function writeLedger(ledger, file = LEDGER_FILE) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(ledger, null, 2), 'utf8');
  fs.renameSync(tmp, file);
}

/** The vault's view of which chat_local instances exist, or null when it is unreachable. NULL and
 *  EMPTY are different answers and the caller must not confuse them: an empty list means "your
 *  instances are gone, re-create them", null means "ask again later". */
async function vaultInstanceIds() {
  try {
    const r = await cc.rawInstances(cc.LOCAL_PROTOCOL);
    return new Set((r.instances || []).map((i) => i.id));
  } catch (e) {
    console.warn('[chat/engine] connections unreachable, instances deferred:', e.message);
    return null;
  }
}

/**
 * Reconcile declared profiles against the database, the vault and the ledger.
 *
 * @returns {Promise<object>} a report — what was created, deferred, repaired or removed. Returned
 *   rather than only logged so the unit tests can assert idempotence directly.
 */
async function reconcile({ store = null, file = APP_JSON, ledgerFile = LEDGER_FILE } = {}) {
  const profiles = store || new ProfileStore();
  const declared = declaredProfiles(file);
  const report = { created: [], deferred: [], repaired: [], removed: [], unchanged: [], errors: [] };
  if (!declared.length) return report;

  const ledger = readLedger(ledgerFile);
  const vault = await vaultInstanceIds();

  const ensureInstance = async (profile, secret, entry) => {
    // The vault secret is BOTH halves of the identity now:
    //   api_key  the credential this service verifies (it keeps only the hash)
    //   nsec     the profile's identity ON THE RELAY — the only thing that can sign as its pubkey
    //
    // Missing them means the vault instance is gone and the ledger no longer holds a copy. The two
    // halves recover DIFFERENTLY, and collapsing them would be a data-loss bug:
    //
    //   api_key  rotate freely. The cost is that clients holding the old one must re-fetch it —
    //            recoverable, and the warning tells them why.
    //   nsec     CANNOT be re-derived. Without it the profile can no longer sign as its pubkey, so
    //            that identity is ALREADY dead; minting a new one is the recovery, not the damage.
    //            But it detaches the profile from everything it signed, so it is announced as the
    //            irreversible thing it is rather than logged as a rotation.
    let sec = secret;
    if (!sec || !sec.api_key || !sec.nsec) {
      const rotated = await profiles.rotate(profile.id);
      console.warn(`[chat/engine] profile ${profile.id}: vault instance missing and its api key was not recoverable — the key has been ROTATED, clients must fetch it again`);
      let nsec = sec && sec.nsec;
      if (!nsec) {
        const reset = await profiles.resetIdentity(profile.id);
        nsec = reset.nsec;
        console.warn(`[chat/engine] profile ${profile.id}: its RELAY IDENTITY was not recoverable either — a NEW keypair has been minted (pubkey ${reset.pubkey.slice(0, 12)}…). Everything the old key signed stays under the OLD pubkey: this profile no longer owns its past messages, channel memberships or read state. This is not reversible.`);
      }
      sec = { profile_id: profile.id, api_key: rotated.key, nsec, pubkey: require('../relay/identity').pubkeyOf(nsec) };
    }
    try {
      const created = await cc.createInstance(
        cc.LOCAL_PROTOCOL, profile.display_name, sec, profile.id);
      const iid = created && created.id;
      if (!iid) throw new Error('connections returned no instance id');
      await profiles.setInstance(profile.id, iid);
      entry.instance_id = iid;
      entry.pending_secret = null;              // the vault has it now; this copy is no longer needed
      // The profile's NAME on the relay (its kind:0) is deliberately NOT published here. This
      // reconciler runs in-process at boot with direct database access and NO network of its own;
      // opening a relay socket from it would make a credential-store step depend on a chat engine
      // being up, and would put I/O in the one path that must never fail the boot. The backend
      // already holds an authenticated socket for exactly this identity — so it publishes its own
      // name on first connect (adapters/buzz.js `_ensureSelfMeta`), which is also self-healing:
      // a relay that was down when the profile was created gets the name on the next op.
      return iid;
    } catch (e) {
      // Hold the WHOLE secret so the NEXT pass creates the instance with the same identity. This is
      // the line that makes "never mint twice" true across a restart while connections is down —
      // and it matters more than it did, because a re-minted nsec is not a re-issued credential,
      // it is a different person.
      entry.pending_secret = sec;
      entry.instance_id = null;
      throw e;
    }
  };

  for (const d of declared) {
    const entry = ledger.profiles[d.id] || { managed: false, instance_id: null, pending_secret: null };
    try {
      let profile = await profiles.get(d.id);

      if (!profile) {
        if (entry.managed === false && ledger.profiles[d.id]) {
          // It was ours, someone deleted it, and it is still declared. Re-creating is the declared
          // state winning, which is what a manifest is for.
        }
        const { profile: made, key, nsec } = await profiles.create({
          id: d.id, display_name: d.display_name, is_admin: d.admin,
        });
        profile = made;
        entry.managed = true;
        entry.created_at = Date.now();
        ledger.profiles[d.id] = entry;
        try {
          await ensureInstance(profile, { profile_id: made.id, api_key: key, nsec, pubkey: made.pubkey }, entry);
          report.created.push(d.id);
        } catch (e) {
          report.deferred.push({ id: d.id, reason: e.message });
          console.warn(`[chat/engine] profile ${d.id} created; its connection is deferred: ${e.message}`);
        }
        continue;
      }

      // The profile exists. Only the ones WE created may be reconciled — an operator's own profile
      // is left exactly as they made it, including its admin flag and its name.
      if (!entry.managed) {
        report.unchanged.push(d.id);
        continue;
      }
      ledger.profiles[d.id] = entry;

      const instanceOk = profile.instance_id
        && (vault === null || vault.has(profile.instance_id));
      if (instanceOk) {
        // BACKFILL — the one state a fresh deployment never reaches and every existing one starts in.
        //
        // A profile created before the relay engine has a row, an api key and a vault instance, but
        // no keypair: its secret is `{profile_id, api_key}` and its `pubkey` column is NULL. It is
        // otherwise perfectly healthy, so the branch above would call it `unchanged` forever, and
        // adapters/index.js would refuse to build it ("no relay identity yet") on every request.
        //
        // Minting one here is NOT the re-minting law 10 forbids: that law protects an identity that
        // EXISTS from being replaced. There is none. It is added, the vault secret is merged rather
        // than replaced so the api key clients already hold keeps working, and setPubkey refuses to
        // overwrite — so a second pass can never turn this into a re-identify.
        if (!profile.pubkey) {
          try {
            const { mintIdentity } = require('../relay/identity');
            const { nsec, pubkey } = mintIdentity();
            const cur = await cc.getSecret(profile.instance_id).catch(() => null);
            const merged = { ...((cur && cur.secret) || {}), profile_id: profile.id, nsec, pubkey };
            if (!merged.api_key) throw new Error('the vault instance carries no api_key to preserve');
            await cc.putSecret(profile.instance_id, merged);
            await profiles.setPubkey(profile.id, pubkey);
            report.repaired.push(d.id);
            console.log(`[chat/engine] profile ${d.id}: minted its relay identity (pubkey ${pubkey.slice(0, 12)}…) — its api key is unchanged`);
            continue;
          } catch (e) {
            report.errors.push({ id: d.id, error: `relay identity backfill: ${e.message}` });
            console.error(`[chat/engine] profile ${d.id}: could not mint a relay identity — ${e.message}`);
            continue;
          }
        }
        report.unchanged.push(d.id);
        continue;
      }
      if (vault === null && !profile.instance_id && !entry.pending_secret) {
        // Nothing to do until connections answers, and nothing may be minted meanwhile.
        report.deferred.push({ id: d.id, reason: 'connections unreachable' });
        continue;
      }
      try {
        await ensureInstance(profile, entry.pending_secret || null, entry);
        report.repaired.push(d.id);
      } catch (e) {
        report.deferred.push({ id: d.id, reason: e.message });
      }
    } catch (e) {
      report.errors.push({ id: d.id, error: e.message });
      console.error(`[chat/engine] profile ${d.id}:`, e.message);
    }
  }

  // Ours, no longer declared → remove the profile and its instance. The person row, their messages
  // and their conversations stay: deleting a profile removes ACCESS, never data.
  const declaredIds = new Set(declared.map((d) => d.id));
  for (const id of Object.keys(ledger.profiles)) {
    if (declaredIds.has(id) || !ledger.profiles[id].managed) continue;
    try {
      const existing = await profiles.get(id);
      if (existing) await profiles.remove(id);
      const iid = (existing && existing.instance_id) || ledger.profiles[id].instance_id;
      if (iid) await cc.deleteInstance(iid).catch(() => {});
      delete ledger.profiles[id];
      report.removed.push(id);
    } catch (e) {
      report.errors.push({ id, error: e.message });
    }
  }

  try { writeLedger(ledger, ledgerFile); } catch (e) {
    console.error('[chat/engine] cannot write the profile ledger:', e.message);
  }
  return report;
}

/**
 * Fire-and-forget entry point for app start.
 *
 * NEVER throws and never fails the boot. A database or a vault that is briefly unreachable is a
 * retry, not an outage of the chat service — and a service that refuses to start because a
 * credential store blinked is a far worse failure than one that comes up with its declared profiles
 * a minute late.
 */
async function start(opts = {}) {
  try {
    const report = await reconcile(opts);
    const say = (k) => (report[k].length ? ` ${k}=${report[k].map((x) => x.id || x).join(',')}` : '');
    console.log(`[chat/engine] profiles reconciled:${say('created')}${say('repaired')}${say('removed')}${say('deferred')}${say('unchanged')}` || '[chat/engine] profiles reconciled: nothing to do');
    return report;
  } catch (e) {
    console.error('[chat/engine] profile reconcile failed (chat still starts):', e.message);
    return null;
  }
}

module.exports = { reconcile, start, declaredProfiles, readLedger, writeLedger, LEDGER_FILE, APP_JSON };
