/**
 * A PROFILE'S IDENTITY ON THE RELAY — one keypair, minted once, never re-minted.
 *
 * The private engine's identity model does not change with the engine swap. A profile is still a
 * row in `chat_profiles` with an admin flag and the HASH of an API key, and the vault still holds
 * the key itself (ai/context/app-engine-pattern.md §2). What buzz adds is that the profile also
 * needs a **Nostr keypair**, because on the relay an identity IS a keypair: the pubkey is who you
 * are to every other participant, and the nsec is the only thing that can sign as you.
 *
 * So the vault secret grows from `{profile_id, api_key}` to `{profile_id, api_key, nsec, pubkey}`.
 * Both halves are minted in the SAME operation as the profile row, for the reason §7 already gives:
 * creating a profile creates its connection, and a profile that exists without one is a step with
 * no decision in it.
 *
 * ── THE ONE RULE THAT MATTERS HERE ───────────────────────────────────────────────────────────
 * `api_key` and `nsec` rotate DIFFERENTLY, and conflating them would be a data-loss bug:
 *
 *   api_key  is a CREDENTIAL. Rotating it locks out clients holding the old one and nothing else.
 *            engine/routes.js exposes exactly that, and it is a normal operation.
 *   nsec     is an IDENTITY. Rotating it does not "re-credential" the profile — it makes it a
 *            DIFFERENT PERSON on the relay. Every message it ever signed stays under the old
 *            pubkey, so its history, its channel memberships and its read state all detach at once
 *            and are unreachable under the new key. There is no un-rotate.
 *
 * That is why `rotate()` in profiles.js touches only the key hash, and why bootstrap's ledger
 * carries the whole secret rather than just the key: law 10 ("never re-mint a key on boot") is now
 * load-bearing for something that cannot be recovered by asking a client to re-fetch.
 */
const { generateSecretKey, getPublicKey } = require('nostr-tools/pure');

/** 32 random bytes, hex — the same shape `openssl rand -hex 32` produces, and what the relay's own
 *  BUZZ_RELAY_PRIVATE_KEY takes. Hex rather than bech32 `nsec1…` because everything that reads it
 *  back (nostr-tools, the relay's config) accepts hex, and one encoding is one fewer thing to get
 *  wrong at a boundary. */
function mintIdentity() {
  const sk = generateSecretKey();
  const nsec = Buffer.from(sk).toString('hex');
  return { nsec, pubkey: getPublicKey(sk) };
}

/** The 64-char lowercase hex pubkey for a stored nsec. Throws on anything that is not a 32-byte
 *  hex string, because a silently-wrong pubkey means a profile that authenticates as nobody. */
function pubkeyOf(nsec) {
  const hex = String(nsec || '').trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(hex)) throw new Error('nsec must be 64 hex characters (32 bytes)');
  return getPublicKey(Buffer.from(hex, 'hex'));
}

/** Bytes for signing. Kept here so no caller has to remember the encoding. */
function secretBytes(nsec) {
  const hex = String(nsec || '').trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(hex)) throw new Error('nsec must be 64 hex characters (32 bytes)');
  return Buffer.from(hex, 'hex');
}

const isPubkey = (v) => /^[0-9a-f]{64}$/.test(String(v || '').toLowerCase());

module.exports = { mintIdentity, pubkeyOf, secretBytes, isPubkey };
