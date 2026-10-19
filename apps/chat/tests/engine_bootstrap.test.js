/**
 * The bootstrap reconciler — declared profiles in app.json become real, credentialed identities.
 *
 * IDEMPOTENCE IS THE WHOLE FEATURE, and the reason it is tested this hard: `bbox run` is run
 * repeatedly against live deployments. A second pass that re-mints a key breaks every client that
 * already stored one, and it does so silently — the vault keeps handing out a credential this
 * service has stopped accepting, so the symptom is a 401 from an account nobody touched.
 *
 * The vault is a Map here, and every secret it is ever handed is recorded, so a re-mint is VISIBLE
 * rather than inferred from a count.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

const { fakeChatDb } = require('./helpers/fake_chat_db');
const { ProfileStore, hashKey } = require('../chatapi/engine/profiles');
const { pubkeyOf } = require('../chatapi/relay/identity');
const bootstrap = require('../chatapi/engine/bootstrap');
const cc = require('../chatapi/connections_client');

const store = () => new ProfileStore({ db: fakeChatDb() });

const DECLARED = {
  id: 'chat',
  engine: {
    id: 'chat_local',
    profiles: [
      { id: 'admin', display_name: 'מנהל', admin: true },
      { id: 'user2', display_name: 'משתמש 2' },
    ],
  },
};

let tmp; let manifest; let ledger; let vault; let minted;

/** A vault that mints ids the way the real one does — `<protocol>-<8hex>`, saying nothing about who
 *  the instance is for. That opacity is the point: an identity can no longer be addressed by
 *  anyone who can spell one. */
function useVault(map) {
  jest.spyOn(cc, 'rawInstances').mockImplementation(async () => ({
    instances: [...map.keys()].map((id) => ({ id, protocol: 'chat_local' })),
  }));
  jest.spyOn(cc, 'createInstance').mockImplementation(async (protocol, label, secret, hint) => {
    const id = `chat_local-${(map.size + 1).toString(16).padStart(8, '0')}`;
    map.set(id, secret);
    minted.push({ id, hint, key: secret.api_key });
    return { id };
  });
  jest.spyOn(cc, 'deleteInstance').mockImplementation(async (id) => { map.delete(id); return { ok: true }; });
}

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-engine-'));
  manifest = path.join(tmp, 'app.json');
  ledger = path.join(tmp, 'engine-profiles.json');
  fs.writeFileSync(manifest, JSON.stringify(DECLARED), 'utf8');
  vault = new Map();
  minted = [];
  useVault(vault);
});

afterEach(() => {
  jest.restoreAllMocks();
  fs.rmSync(tmp, { recursive: true, force: true });
});

test('a declared profile becomes BOTH a profile row and a vault instance with a credential', async () => {
  const s = store();
  const r = await bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger });
  expect(r.created.sort()).toEqual(['admin', 'user2']);

  const admin = await s.get('admin');
  expect(admin).toMatchObject({ id: 'admin', is_admin: true, status: 'active' });
  expect(admin.instance_id).toMatch(/^chat_local-[0-9a-f]{8}$/);

  // The vault holds the KEY, this service holds only its hash, and the two agree.
  const secret = vault.get(admin.instance_id);
  expect(secret.profile_id).toBe('admin');
  expect(secret.api_key).toMatch(/^chatp_[0-9a-f]{64}$/);
  expect((await s.byKey(secret.api_key)).id).toBe('admin');
  expect(s.db._profiles.get('admin').key_hash).toBe(hashKey(secret.api_key));

  // Only the declared admin is an admin, and the second profile got its own distinct credential.
  const user2 = await s.get('user2');
  expect(user2.is_admin).toBe(false);
  expect(vault.get(user2.instance_id).api_key).not.toBe(secret.api_key);
});

test('a second and third pass change NOTHING — a key is never re-minted', async () => {
  const s = store();
  await bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger });
  const instancesBefore = [...vault.entries()].map(([id, sec]) => [id, sec.api_key]);
  const hashesBefore = [...s.db._profiles.values()].map((p) => [p.id, p.key_hash]);
  const mintsBefore = minted.length;

  const second = await bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger });
  expect(second.created).toEqual([]);
  expect(second.repaired).toEqual([]);
  expect(second.unchanged.sort()).toEqual(['admin', 'user2']);

  await bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger });

  expect(minted.length).toBe(mintsBefore);
  expect([...vault.entries()].map(([id, sec]) => [id, sec.api_key])).toEqual(instancesBefore);
  expect([...s.db._profiles.values()].map((p) => [p.id, p.key_hash])).toEqual(hashesBefore);
});

test('connections unreachable: the profile exists, the instance is deferred, and the SAME key is used on the retry', async () => {
  const s = store();
  cc.createInstance.mockRejectedValue(new Error('connections unreachable'));
  cc.rawInstances.mockRejectedValue(new Error('connections unreachable'));

  const first = await bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger });
  expect(first.deferred.map((d) => d.id).sort()).toEqual(['admin', 'user2']);

  const admin = await s.get('admin');
  expect(admin).not.toBeNull();          // the profile survives a vault outage
  expect(admin.instance_id).toBeNull();  // …and is honestly not selectable yet
  const hashBefore = s.db._profiles.get('admin').key_hash;

  // The whole SECRET is held on the APP'S OWN VOLUME so the retry can use the same one. This is
  // what makes "never mint twice" true across a restart while connections is down — and it matters
  // more than it used to, because the secret now carries the profile's RELAY IDENTITY as well as
  // its credential. A re-minted api key locks clients out until they re-fetch; a re-minted nsec is
  // a different person on the relay, and there is no un-rotate (chatapi/relay/identity.js).
  const held = JSON.parse(fs.readFileSync(ledger, 'utf8')).profiles.admin.pending_secret;
  expect(held.api_key).toMatch(/^chatp_/);
  expect(hashKey(held.api_key)).toBe(hashBefore);
  expect(held.nsec).toMatch(/^[0-9a-f]{64}$/);
  expect(held.pubkey).toBe(pubkeyOf(held.nsec));
  expect(held.pubkey).toBe(admin.pubkey);        // …and it is the identity the profile row claims

  // The vault comes back.
  jest.restoreAllMocks();
  const later = new Map();
  useVault(later);
  const second = await bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger });
  expect(second.repaired.sort()).toEqual(['admin', 'user2']);

  expect(s.db._profiles.get('admin').key_hash).toBe(hashBefore);      // not rotated
  const restored = [...later.values()].find((x) => x.profile_id === 'admin');
  expect(restored.api_key).toBe(held.api_key);                        // the very same key
  expect(restored.nsec).toBe(held.nsec);                              // …and the very same identity
  // …and the app stops keeping a copy the moment the vault has one.
  expect(JSON.parse(fs.readFileSync(ledger, 'utf8')).profiles.admin.pending_secret).toBeNull();
});

test('un-declaring a profile removes it; a profile we never created is LEFT ALONE', async () => {
  const s = store();
  await bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger });

  // An operator adds one by hand through the profile screen. It is not in the ledger, so it is not
  // ours, and a redeploy must never delete it.
  const hand = await s.create({ id: 'made-by-hand', display_name: 'ידני' });
  await s.setInstance('made-by-hand', 'chat_local-ffffffff');

  fs.writeFileSync(manifest, JSON.stringify({
    id: 'chat',
    engine: { id: 'chat_local', profiles: [{ id: 'admin', display_name: 'מנהל', admin: true }] },
  }), 'utf8');
  const r = await bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger });

  expect(r.removed).toEqual(['user2']);
  expect(await s.get('user2')).toBeNull();
  expect(await s.get('made-by-hand')).not.toBeNull();
  expect((await s.byKey(hand.key)).id).toBe('made-by-hand');
});

test('a manifest with no engine block is a no-op, not an error', async () => {
  const s = store();
  fs.writeFileSync(manifest, JSON.stringify({ id: 'chat' }), 'utf8');
  await expect(bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger }))
    .resolves.toMatchObject({ created: [], errors: [] });
});

test('an unreadable manifest costs the declared profiles, not the boot', async () => {
  const s = store();
  fs.writeFileSync(manifest, '{ not json', 'utf8');
  await expect(bootstrap.reconcile({ store: s, file: manifest, ledgerFile: ledger }))
    .resolves.toMatchObject({ created: [], errors: [] });
});
