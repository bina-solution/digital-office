/**
 * The adapter layer: which chat backend answers THIS request.
 *
 * This is the same shape mail arrived at in apps/mail/mailapi/adapters.py, deliberately rather than
 * by coincidence. Mail solved exactly this problem — several providers behind one API, one selected
 * account, per-call overrides — and two of its rules are the reason it works:
 *
 *   1. ONE choke point. Every op resolves its backend here, so "which account is this?" has exactly
 *      one answer and /readyz cannot disagree with the ops. Mail's predecessor picked the backend
 *      from an env var at process start, which made the protocol a BUILD-TIME property: selecting a
 *      connection could not change what an op did.
 *   2. Cache by CREDENTIAL, not by id. A rotated token keeps its connection id and leaves every
 *      socket dead. Fingerprinting the secret is what makes rotation take effect without a restart.
 *
 * Protocols → backend:
 *   chat_local        BuzzChatBackend    the platform's own chat, on a buzz relay we run
 *                                        (users, groups, media, mentions, read state, presence)
 *   chat_wa_baileys   BaileysBackend     WhatsApp via Baileys — the pairing this app already had
 *   chat_tg_bot       TelegramBackend    Telegram Bot API, token from the vault
 */
const crypto = require('crypto');

const cc = require('../connections_client');

/**
 * THE OP SURFACE. This dict IS the contract: /manifest advertises its keys and server.js dispatches
 * through it, so the advertisement and the implementation cannot drift. Mail learned this the hard
 * way — its manifest hand-listed eight ops while the service had grown four more, so the ops the
 * automation layer needed were undiscoverable and one was unreachable to anyone who trusted the
 * contract.
 *
 * op name -> the backend method that answers it.
 */
const CANONICAL_OPS = {
  listConversations: 'listConversations',
  getConversation: 'getConversation',
  sendMessage: 'sendMessage',
  markRead: 'markRead',
  probe: 'probe',
};

/** Ops only SOME protocols implement. Advertised separately so a caller can tell "this service
 *  cannot do that" from "this connection cannot do that" BEFORE trying. */
const PROTOCOL_OPS = {
  reconnect: 'reconnect',       // QR / token re-pair — meaningless for local chat
  listGroups: 'listGroups',
  createGroup: 'createGroup',
  uploadMedia: 'uploadMedia',
  // Starting a conversation is PROTOCOL, not canonical, because the address book is not always
  // enumerable: Baileys has no "list every contact" call, and a Telegram bot may only speak to
  // users who wrote to it first. Canonical would force those two to invent an answer; optional lets
  // opsFor() advertise them only where they are real, so the UI hides "new chat" rather than
  // offering a button that can only fail.
  listUsers: 'listUsers',
  createDirect: 'createDirect',
  // Push. Optional for the same reason: local chat can be told by Postgres the instant a row lands,
  // while Baileys and Telegram have their own event streams. A backend without it does not advertise
  // it and the client falls back to polling — slower, not broken.
  subscribe: 'subscribe',
};

/** The ops a given backend actually answers — derived by ASKING the object, so a backend that loses
 *  a method stops advertising it rather than advertising a 500. */
function opsFor(backend) {
  const has = (m) => typeof backend[m] === 'function';
  return [
    ...Object.keys(CANONICAL_OPS).filter((k) => has(CANONICAL_OPS[k])),
    ...Object.keys(PROTOCOL_OPS).filter((k) => has(PROTOCOL_OPS[k])),
  ];
}

/**
 * The connection cannot be turned into a working backend (unknown id/protocol, vault down with
 * nothing cached, missing token).
 *
 * It carries WHICH connection failed, and that is not a detail. Every op accepts a per-call
 * connectionId override, so the failing connection is frequently NOT the active one. Mail's error
 * handler reported the active id regardless, and produced answers naming two different accounts —
 * with the wrong one in the field a machine reads.
 */
class AdapterError extends Error {
  constructor(message, status = 502, connectionId = null) {
    super(message);
    this.name = 'AdapterError';
    this.status = status;
    this.connectionId = connectionId;
  }
}

// ── caches ────────────────────────────────────────────────────────────────────
// A secret lookup is an HTTP call to the vault and ops run often, so resolution is cached briefly:
// short enough that a rotated credential takes effect on its own, long enough that the vault is not
// in the hot path of every message poll.
const SECRET_TTL_MS = Number(process.env.CHAT_SECRET_TTL_MS || 30000);
const _backends = new Map();   // connection id -> { fingerprint, backend }
const _secrets = new Map();    // connection id -> { at, protocol, secret }

/** Identity of the CREDENTIAL, not of the connection — see the header. */
function fingerprint(protocol, secret) {
  return crypto.createHash('sha256')
    .update(JSON.stringify({ p: protocol, s: secret || {} }))
    .digest('hex');
}

/**
 * (protocol, secret) for a connection id, TTL-cached.
 *
 * Two failures that look alike and must not be treated alike:
 *   · the vault is UNREACHABLE — fall back to the last known values. An op must not fail because
 *     the vault blinked, and the credential we already hold is still the right one.
 *   · the vault says 404 — the instance is GONE. That is authoritative, so the cache is now a lie:
 *     drop it and fail. Serving a deleted account's cached token would keep chat running on
 *     credentials the operator believes they removed.
 *
 * `explicit` distinguishes a caller naming an id that does not exist (404, their mistake) from the
 * ACTIVE POINTER dangling (503 — the service is not ready, which is what /readyz must report and
 * must never answer by substituting another account).
 */
async function fetchCredential(cid, explicit = false) {
  const hit = _secrets.get(cid);
  if (hit && Date.now() - hit.at < SECRET_TTL_MS) return hit;
  try {
    const r = await cc.getSecret(cid);
    const rec = { at: Date.now(), protocol: r.protocol || '', secret: r.secret || {} };
    _secrets.set(cid, rec);
    return rec;
  } catch (e) {
    if (e.status === 404) {
      _secrets.delete(cid);
      throw new AdapterError(
        `החיבור שנבחר (${cid}) אינו קיים יותר. בחר חיבור אחר או חבר אותו מחדש.`,
        explicit ? 404 : 503, cid);
    }
    if (hit) return hit;
    throw new AdapterError(`לא ניתן לאמת את החיבור שנבחר (${cid}): ${e.message}`, 503, cid);
  }
}

function build(cid, protocol, secret) {
  // Required lazily so one broken backend module cannot stop the service from serving the others,
  // and so the pure parts of this file stay importable without a driver installed.
  if (protocol === cc.LOCAL_PROTOCOL) {
    const { BuzzChatBackend } = require('./buzz');
    // `profile_id` and `nsec` both come from the VAULT INSTANCE, never from anything a caller sent
    // and never from the instance id (which is `chat_local-<8hex>` like every other instance and
    // says nothing about identity).
    //
    // The nsec is what makes this a real credential rather than a name: on the relay an identity IS
    // a keypair, so a local profile now carries a secret exactly like a Gmail app password does.
    // That is the unification app-engine-pattern.md §2 asks for — private and remote resolve the
    // same way, and the ~6 special cases per app the synthetic local instance forced are gone.
    //
    // Safe to cache per connection id: _backends is keyed on cid, so two profiles on the same engine
    // get two backends rather than sharing one and showing each other's messages as their own.
    const selfId = secret && secret.profile_id;
    if (!selfId) throw new AdapterError(`connection ${cid}: no profile behind this local instance`, 502, cid);
    if (!secret.nsec) {
      throw new AdapterError(
        `connection ${cid}: the local profile has no relay identity yet — it is minted at boot by ` +
        `chatapi/engine/bootstrap.js; restart the chat service or re-declare the profile`, 502, cid);
    }
    return new BuzzChatBackend({ selfId, nsec: secret.nsec, profiles: profiles() });
  }
  if (protocol === 'chat_wa_baileys') {
    const { BaileysBackend } = require('./baileys');
    return new BaileysBackend(secret || {});
  }
  if (protocol === 'chat_tg_bot') {
    const token = secret && (secret.token || secret.bot_token);
    if (!token) throw new AdapterError(`connection ${cid}: secret needs {token}`, 502, cid);
    const { TelegramBackend } = require('./telegram');
    return new TelegramBackend(token);
  }
  throw new AdapterError(`connection ${cid}: unsupported protocol ${protocol}`, 400, cid);
}

/** The app's own profile table. Lazily constructed so this module stays importable with no database
 *  driver, which is what keeps the pure parts unit-testable. */
let _profiles = null;
function profiles() {
  if (!_profiles) {
    const { ProfileStore } = require('../engine/profiles');
    _profiles = new ProfileStore();
  }
  return _profiles;
}

/** Test seam + the hook adapters use to share one store with the routes. */
function useProfiles(store) { _profiles = store; }

/**
 * THE ONE RESOLUTION CHOKE POINT — (connectionId, backend, profile) for this request.
 *
 * Precedence: explicit per-op connectionId > the binding > the first admin profile. There is no
 * fallback past that: a BROKEN pointer raises 503 rather than quietly serving a different account.
 * An UNSET pointer means "use the default engine"; a broken one means "not ready", and collapsing
 * those two is how a service comes to report ready:true while the owner believes they selected their
 * WhatsApp account.
 *
 * PRIVATE AND REMOTE ARE RESOLVED THE SAME WAY. The only difference is where the profile identity
 * comes from: for a private instance this service owns the profile row, so it reads it directly and
 * does not need the vault to tell it who it is — the vault's copy of that key exists so CLIENTS can
 * fetch it, and a vault outage must not stop the engine we run ourselves. For a remote instance the
 * secret IS the identity and comes from the vault, exactly as before.
 */
async function resolveActive(connectionId = null) {
  const explicit = Boolean(connectionId);
  let cid = connectionId || (await cc.active()) || null;

  let profile = null;
  if (cid) {
    profile = await profiles().byInstance(cid).catch(() => null);
  } else {
    // Nothing bound: the default is the first admin profile on the private engine.
    profile = await profiles().firstAdmin().catch(() => null);
    if (!profile || !profile.instance_id) {
      throw new AdapterError(
        'לא נבחר חיבור ואין עדיין פרופיל מנהל עם חיבור במנוע הפנימי', 503, null);
    }
    cid = profile.instance_id;
  }

  if (profile) {
    if (profile.status !== 'active') {
      throw new AdapterError(`הפרופיל «${profile.display_name}» מושהה`, 403, cid);
    }
    // PRIVATE AND REMOTE NOW RESOLVE IDENTICALLY, and that is the point of the engine swap.
    //
    // This used to build straight from the profile row, on the reasoning that "a vault outage must
    // not stop the engine we run ourselves". That held while the local identity was just a NAME.
    // It is a keypair now, the vault is its only home, and there is nothing to build a backend from
    // without it — so the local path fetches its credential like every other backend.
    //
    // A vault BLINK still does not stop chat: fetchCredential falls back to the last known values
    // when connections is unreachable, and an already-built backend is served from the fingerprint
    // cache without asking at all. What is refused is the case that must be refused — a vault 404,
    // meaning the instance is GONE, where serving a cached identity would act as a profile the
    // operator believes they removed.
    const { secret } = await fetchCredential(cid, explicit);
    const fp = fingerprint(cc.LOCAL_PROTOCOL, { p: profile.id, h: profile.key_fp, k: secret && secret.pubkey });
    const hit = _backends.get(cid);
    if (hit && hit.fingerprint === fp) return { cid, backend: hit.backend, profile };
    const backend = build(cid, cc.LOCAL_PROTOCOL, { ...(secret || {}), profile_id: profile.id });
    if (hit && typeof hit.backend.close === 'function') {
      try { await hit.backend.close(); } catch { /* the identity changed; the old socket is dead anyway */ }
    }
    _backends.set(cid, { fingerprint: fp, backend });
    return { cid, backend, profile };
  }

  const { protocol, secret } = await fetchCredential(cid, explicit);
  if (protocol === cc.LOCAL_PROTOCOL) {
    // A chat_local instance the profile table does not know: the vault row outlived its profile.
    // Serving it would be acting as an identity this engine has deliberately removed access to.
    throw new AdapterError(
      `החיבור (${cid}) אינו מקושר לפרופיל קיים במנוע הפנימי`, explicit ? 404 : 503, cid);
  }
  const fp = fingerprint(protocol, secret);

  const hit = _backends.get(cid);
  if (hit && hit.fingerprint === fp) return { cid, backend: hit.backend, profile: null };

  const backend = build(cid, protocol, secret);
  _backends.set(cid, { fingerprint: fp, backend });
  if (hit && typeof hit.backend.close === 'function') {
    try { await hit.backend.close(); } catch { /* the credential changed; the old sockets are dead anyway */ }
  }
  return { cid, backend, profile: null };
}

/** Drop a connection's cached backend + secret (it was deleted or re-selected away). */
async function forget(cid) {
  const hit = _backends.get(cid);
  _backends.delete(cid);
  _secrets.delete(cid);
  if (hit && typeof hit.backend.close === 'function') {
    try { await hit.backend.close(); } catch { /* nothing to salvage */ }
  }
}

module.exports = {
  CANONICAL_OPS, PROTOCOL_OPS, opsFor, AdapterError,
  resolveActive, forget, fingerprint, profiles, useProfiles,
};
