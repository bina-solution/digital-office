/**
 * The private engine's profile contract — credential, rings, and the reconciler's idempotence.
 *
 * Driven against an in-memory stand-in for Postgres rather than a real one, because every rule under
 * test is a DECISION and not a query plan: who a key resolves to, whether a credential may act as
 * somebody else, whether the last admin can be demoted, and whether a second boot re-mints. A real
 * database would test node-postgres. The SQL-level scoping is asserted separately, against the live
 * stack, because that one genuinely is about the query.
 */
const express = require('express');
const request = require('supertest');

const { ProfileStore, ProfileError, hashKey } = require('../chatapi/engine/profiles');
const { makeAuth } = require('../chatapi/engine/auth');
const engineRoutes = require('../chatapi/engine/routes');

const { fakeChatDb } = require('./helpers/fake_chat_db');

const store = () => new ProfileStore({ db: fakeChatDb() });

// ── the credential ──────────────────────────────────────────────────────────────────────────────

describe('a private profile holds a credential', () => {
  test('creating one mints a key and stores only its hash', async () => {
    const s = store();
    const { profile, key } = await s.create({ id: 'admin', display_name: 'מנהל', is_admin: true });
    expect(key).toMatch(/^chatp_[0-9a-f]{64}$/);
    expect(profile).toMatchObject({ id: 'admin', is_admin: true, status: 'active' });
    // The key itself is nowhere in the stored row — only its digest.
    const row = s.db._profiles.get('admin');
    expect(row.key_hash).toBe(hashKey(key));
    expect(JSON.stringify(row)).not.toContain(key);
    // …and it never comes back out through the public shape either.
    expect(JSON.stringify(profile)).not.toContain(key);
    expect(profile.key_hash).toBeUndefined();
  });

  test('the key resolves to its profile, and nothing else does', async () => {
    const s = store();
    const { key } = await s.create({ id: 'admin', display_name: 'מנהל', is_admin: true });
    expect((await s.byKey(key)).id).toBe('admin');
    expect(await s.byKey('chatp_' + '0'.repeat(64))).toBeNull();
    expect(await s.byKey('')).toBeNull();
  });

  test('a profile is created exactly once — a second create is a 409, not a re-mint', async () => {
    const s = store();
    const first = await s.create({ id: 'admin', display_name: 'מנהל', is_admin: true });
    await expect(s.create({ id: 'admin', display_name: 'מנהל' })).rejects.toThrow(ProfileError);
    expect((await s.byKey(first.key)).id).toBe('admin');   // the original key still works
  });

  test('rotation invalidates the old key and only the old key', async () => {
    const s = store();
    const a = await s.create({ id: 'admin', display_name: 'מנהל', is_admin: true });
    const b = await s.create({ id: 'user2', display_name: 'משתמש 2' });
    const rotated = await s.rotate('admin');
    expect(await s.byKey(a.key)).toBeNull();
    expect((await s.byKey(rotated.key)).id).toBe('admin');
    expect((await s.byKey(b.key)).id).toBe('user2');       // untouched
    // The fingerprint the adapter caches on must move, or a rotated profile keeps serving.
    expect(rotated.profile.key_fp).not.toBe(a.profile.key_fp);
  });

  test('a profile id is a slug — anything else is refused before it reaches SQL', async () => {
    const s = store();
    for (const bad of ['a b', 'user/2', '../etc', '', 'שם', 'user.2']) {
      await expect(s.create({ id: bad, display_name: 'x' })).rejects.toThrow(/profile id/);
    }
  });

  test('case is normalised, not rejected — "Admin" and "admin" must not be two identities', async () => {
    // The id lands in a chat_users primary key, an account_hint and a URL segment. Two rows differing
    // only in case would be two profiles the operator reads as one, each with its own credential.
    const s = store();
    const { profile } = await s.create({ id: 'Admin', display_name: 'מנהל', is_admin: true });
    expect(profile.id).toBe('admin');
    await expect(s.create({ id: 'ADMIN', display_name: 'x' })).rejects.toThrow(/already exists/);
  });
});

// ── the last admin ──────────────────────────────────────────────────────────────────────────────

describe('the last admin', () => {
  const seed = async () => {
    const s = store();
    await s.create({ id: 'admin', display_name: 'מנהל', is_admin: true });
    await s.create({ id: 'user2', display_name: 'משתמש 2' });
    return s;
  };

  test('cannot be demoted', async () => {
    const s = await seed();
    await expect(s.update('admin', { is_admin: false })).rejects.toThrow(/last admin/);
    expect((await s.get('admin')).is_admin).toBe(true);
  });

  test('cannot be suspended', async () => {
    const s = await seed();
    await expect(s.update('admin', { status: 'suspended' })).rejects.toThrow(/last admin/);
  });

  test('cannot be removed', async () => {
    const s = await seed();
    await expect(s.remove('admin')).rejects.toThrow(/last admin/);
    expect(await s.get('admin')).not.toBeNull();
  });

  test('a SECOND admin makes the first removable again', async () => {
    const s = await seed();
    await s.update('user2', { is_admin: true });
    await expect(s.update('admin', { is_admin: false })).resolves.toMatchObject({ is_admin: false });
    // …and now user2 is the last one.
    await expect(s.remove('user2')).rejects.toThrow(/last admin/);
  });

  test('a non-admin is removable, and removing it removes ACCESS only', async () => {
    const s = await seed();
    const before = await s.get('user2');
    const r = await s.remove('user2');
    expect(r.ok).toBe(true);
    expect(await s.get('user2')).toBeNull();
    // Its history is not this database's to delete: every message that identity signed lives on the
    // relay under its pubkey, in an append-only log signed by a key this service does not keep. The
    // old `chat_users` row was the local half of that promise; the pubkey is what carries it now.
    expect(before.pubkey).toMatch(/^[0-9a-f]{64}$/);
  });
});

// ── the rings, over HTTP ────────────────────────────────────────────────────────────────────────

describe('the rings', () => {
  async function harness() {
    const s = store();
    const admin = await s.create({ id: 'admin', display_name: 'מנהל', is_admin: true });
    const user2 = await s.create({ id: 'user2', display_name: 'משתמש 2' });
    await s.setInstance('admin', 'chat_local-a1a1a1a1');
    await s.setInstance('user2', 'chat_local-b2b2b2b2');

    let bound = null;
    const cc = {
      LOCAL_PROTOCOL: 'chat_local',
      active: async () => bound,
      select: async (id) => { bound = id; return id; },
      createInstance: async () => ({ id: `chat_local-${Math.random().toString(16).slice(2, 10)}` }),
      putSecret: async () => ({ ok: true }),
      deleteInstance: async () => ({ ok: true }),
    };
    const auth = makeAuth({ profiles: s, cc });
    const app = express();
    app.use(express.json());
    engineRoutes.register(app, (req, res, next) => next(), {
      profiles: s, cc, auth, adapters: { forget: async () => {} },
    });
    return { app, s, adminKey: admin.key, userKey: user2.key, bind: (id) => { bound = id; } };
  }

  test('admin ring: an ordinary profile cannot create another profile', async () => {
    const h = await harness();
    const r = await request(h.app).post('/engine/profiles')
      .set('X-Chat-Profile-Key', h.userKey).send({ id: 'user3', display_name: 'משתמש 3' });
    expect(r.status).toBe(403);
    expect(r.body.error).toMatch(/הרשאת ניהול/);
    expect(await h.s.get('user3')).toBeNull();
  });

  test('admin ring: an admin creates a profile AND its connection in one operation', async () => {
    const h = await harness();
    const r = await request(h.app).post('/engine/profiles')
      .set('X-Chat-Profile-Key', h.adminKey).send({ id: 'user3', display_name: 'משתמש 3' });
    expect(r.status).toBe(201);
    expect(r.body.key).toMatch(/^chatp_[0-9a-f]{64}$/);
    expect(r.body.connection_id).toMatch(/^chat_local-/);
    expect((await h.s.get('user3')).instance_id).toBe(r.body.connection_id);
  });

  test('a credential can only ever act as itself', async () => {
    const h = await harness();
    // user2's key, naming the ADMIN's connection.
    const r = await request(h.app).get('/engine/whoami?connection_id=chat_local-a1a1a1a1')
      .set('X-Chat-Profile-Key', h.userKey);
    expect(r.status).toBe(403);
    expect(r.body.error).toMatch(/משתמש 2/);
  });

  test('an unknown credential is 401, not a silent fallback to the default profile', async () => {
    const h = await harness();
    const r = await request(h.app).get('/engine/whoami').set('X-Chat-Profile-Key', 'chatp_deadbeef');
    expect(r.status).toBe(401);
  });

  test('self ring: a profile may rotate its own key but not another profile’s', async () => {
    const h = await harness();
    const mine = await request(h.app).post('/engine/profiles/user2/key').set('X-Chat-Profile-Key', h.userKey);
    expect(mine.status).toBe(200);
    expect(mine.body.key).toMatch(/^chatp_/);

    const theirs = await request(h.app).post('/engine/profiles/admin/key').set('X-Chat-Profile-Key', mine.body.key);
    expect(theirs.status).toBe(403);
  });

  test('self ring: a profile cannot promote itself', async () => {
    const h = await harness();
    const r = await request(h.app).patch('/engine/profiles/user2')
      .set('X-Chat-Profile-Key', h.userKey).send({ is_admin: true });
    expect(r.status).toBe(403);
    expect((await h.s.get('user2')).is_admin).toBe(false);
  });

  test('the binding decides the acting profile when no credential is presented', async () => {
    const h = await harness();
    h.bind('chat_local-b2b2b2b2');
    const r = await request(h.app).get('/engine/whoami');
    expect(r.body).toMatchObject({ is_admin: false, credentialed: false });
    expect(r.body.profile.id).toBe('user2');
    // …and that session then cannot administer profiles either.
    const denied = await request(h.app).get('/engine/profiles');
    expect(denied.status).toBe(403);
  });

  test('DELETE removes access and says so — it never claims to have removed data', async () => {
    const h = await harness();
    const r = await request(h.app).delete('/engine/profiles/user2').set('X-Chat-Profile-Key', h.adminKey);
    expect(r.status).toBe(200);
    // `data_kept` is the whole claim, and it is now structurally true rather than a promise this
    // service keeps: the messages are on the relay, under a pubkey, in a log it cannot rewrite.
    expect(r.body).toMatchObject({ ok: true, id: 'user2', data_kept: true });
  });
});

// ── the bug the live stack found ────────────────────────────────────────────────────────────────

describe('a credential is self-addressing', () => {
  /**
   * Measured against the running deployment, not imagined: nothing was bound, a request carried
   * user2's key and no connection_id, `withActor` resolved the actor as user2 — and the op handler
   * then re-derived the connection on its own, saw no binding, fell back to the first admin, and
   * answered with the ADMIN's conversations. The credential was checked and then ignored.
   *
   * Two rules come out of it, and both are tested here:
   *   · the actor's connection is decided ONCE, by withActor, and ops read that field;
   *   · a credential ignores the binding entirely — the binding is a browser-session concept and a
   *     human clicking the switcher must not redirect every automation on the deployment.
   */
  async function harness(bound) {
    const s = store();
    const admin = await s.create({ id: 'admin', display_name: 'מנהל', is_admin: true });
    const user2 = await s.create({ id: 'user2', display_name: 'משתמש 2' });
    await s.setInstance('admin', 'chat_local-aaaaaaaa');
    await s.setInstance('user2', 'chat_local-bbbbbbbb');
    const cc = { LOCAL_PROTOCOL: 'chat_local', active: async () => bound, select: async () => bound };
    const auth = makeAuth({ profiles: s, cc });
    const app = express();
    app.use(express.json());
    // A stand-in for an op route: it reports the connection the ops layer would actually use.
    app.get('/op', auth.withActor, (req, res) => res.json({
      actor: req.actor && req.actor.id, connection: req.actorConnection,
    }));
    return { app, admin: admin.key, user2: user2.key };
  }

  test('with the app bound to the ADMIN, user2\'s key still acts as user2', async () => {
    const h = await harness('chat_local-aaaaaaaa');
    const r = await request(h.app).get('/op').set('X-Chat-Profile-Key', h.user2);
    expect(r.body).toEqual({ actor: 'user2', connection: 'chat_local-bbbbbbbb' });
  });

  test('with NOTHING bound, user2\'s key does not fall back to the first admin', async () => {
    const h = await harness(null);
    const r = await request(h.app).get('/op').set('X-Chat-Profile-Key', h.user2);
    expect(r.body).toEqual({ actor: 'user2', connection: 'chat_local-bbbbbbbb' });
  });

  test('with nothing bound and NO credential, the session path does fall back to the first admin', async () => {
    const h = await harness(null);
    const r = await request(h.app).get('/op');
    expect(r.body).toEqual({ actor: 'admin', connection: 'chat_local-aaaaaaaa' });
  });

  test('naming your own connection is fine; naming someone else\'s is 403', async () => {
    const h = await harness(null);
    const mine = await request(h.app).get('/op?connection_id=chat_local-bbbbbbbb').set('X-Chat-Profile-Key', h.user2);
    expect(mine.body).toEqual({ actor: 'user2', connection: 'chat_local-bbbbbbbb' });
    const theirs = await request(h.app).get('/op?connection_id=chat_local-aaaaaaaa').set('X-Chat-Profile-Key', h.user2);
    expect(theirs.status).toBe(403);
  });

  test('a profile key cannot borrow a REMOTE connection', async () => {
    // The key says "I am user2 on the private engine". It is not a licence to drive the company
    // WhatsApp number, and silently letting it would be a privilege nobody granted.
    const h = await harness(null);
    const r = await request(h.app).get('/op?connection_id=chat_wa_baileys-9f9f9f9f').set('X-Chat-Profile-Key', h.user2);
    expect(r.status).toBe(403);
    expect(r.body.error).toMatch(/חיצוני/);
  });
});
