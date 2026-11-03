/**
 * The local chat backend against a REAL relay.
 *
 * This file replaces `tests/local_chat_db.test.js` and keeps its bargain exactly: `present.test.js`
 * proves the projection with no engine at all, and THIS proves the half a fake cannot — that the
 * kinds are the right kinds, that a roster really carries the member we added, that a message sent
 * through the backend comes back out of the relay in the shape the client renders, and that an
 * attachment can be uploaded and fetched back byte-for-byte. A mapping bug is caught by the pure
 * tests; a wrong kind number, a missing mandatory header or a tag the relay ignores is caught only
 * here.
 *
 * SKIPPED BY DEFAULT. It needs a relay, and a unit suite that fails on a laptop with no stack
 * running teaches people to ignore red. The relay is not published on the host, so run it INSIDE
 * the docker network:
 *
 *   docker run --rm --network traefik-network \
 *     -v /path/to/deployment-hacohen/apps/chat:/app -w /app \
 *     -e CHAT_RELAY_TEST=1 node:22-slim npx jest tests/buzz_backend.test.js
 *
 * Every identity it uses is minted fresh per run, so it can run against the live relay without
 * touching a real profile's history.
 */
const enabled = process.env.CHAT_RELAY_TEST === '1';
const d = enabled ? describe : describe.skip;

/* eslint-disable global-require */
const { BuzzChatBackend } = require('../chatapi/adapters/buzz');
const { mintIdentity } = require('../chatapi/relay/identity');

/** A ProfileStore stand-in: just the two lookups the backend actually uses. */
function fakeProfiles(rows) {
  return {
    async list() { return rows; },
    async get(id) { return rows.find((r) => r.id === id) || null; },
    async byPubkey(pk) { return rows.find((r) => r.pubkey === pk) || null; },
  };
}

d('BuzzChatBackend against a live relay', () => {
  jest.setTimeout(60000);

  let alice; let bob; let profiles; let A; let B;

  beforeAll(async () => {
    A = { id: 'alice', ...mintIdentity() };
    B = { id: 'bob', ...mintIdentity() };
    profiles = fakeProfiles([
      { id: 'alice', display_name: 'אליס', pubkey: A.pubkey, status: 'active' },
      { id: 'bob', display_name: 'בוב', pubkey: B.pubkey, status: 'active' },
    ]);
    alice = new BuzzChatBackend({ selfId: 'alice', nsec: A.nsec, profiles });
    bob = new BuzzChatBackend({ selfId: 'bob', nsec: B.nsec, profiles });
  });

  afterAll(async () => {
    if (alice) await alice.close();
    if (bob) await bob.close();
  });

  test('probe reports reachable, and names the identity it is acting as', async () => {
    const p = await alice.probe();
    expect(p.ok).toBe(true);
    expect(p.reachable).toBe(true);
    expect(p.protocol).toBe('chat_local');
    expect(p.self).toEqual({ id: 'alice', pubkey: A.pubkey });
  });

  test('createGroup: the group exists, and the member we added is really in its roster', async () => {
    const g = await alice.createGroup({ name: 'קבוצת בדיקה', members: ['bob'] });
    expect(g.ok).toBe(true);
    const groups = await alice.listGroups();
    const mine = groups.find((c) => c.id === g.id);
    expect(mine).toBeTruthy();
    expect(mine.group).toBe(true);
    expect(mine.name).toBe('קבוצת בדיקה');
    // and bob sees it from his own identity — the roster is the relay's, not our cache
    const his = await bob.listConversations();
    expect(his.some((c) => c.id === g.id)).toBe(true);
  });

  test('sendMessage persists and comes back in the thread, in the rendered shape', async () => {
    const g = await alice.createGroup({ name: 'שיחה', members: ['bob'] });
    const sent = await alice.sendMessage(g.id, { text: 'שלום מאליס' });
    expect(sent.ok).toBe(true);
    expect(sent.message.dir).toBe('out');

    const thread = await alice.getConversation(g.id);
    const found = thread.messages.find((m) => m.id === sent.message.id);
    expect(found).toBeTruthy();
    expect(found.text).toBe('שלום מאליס');   // Hebrew round-trips
    expect(found.dir).toBe('out');

    // …and to BOB the same message is inbound, attributed to a profile slug and not a raw pubkey
    const his = await bob.getConversation(g.id);
    const seen = his.messages.find((m) => m.id === sent.message.id);
    expect(seen.dir).toBe('in');
    expect(seen.sender).toBe('אליס');
  });

  test('unread counts inbound only, and markRead clears it', async () => {
    const g = await alice.createGroup({ name: 'ספירה', members: ['bob'] });
    await bob.sendMessage(g.id, { text: 'אחת' });
    await bob.sendMessage(g.id, { text: 'שתיים' });

    const before = (await alice.listConversations()).find((c) => c.id === g.id);
    expect(before.unread).toBe(2);
    expect(before.lastDir).toBe('in');
    expect(before.lastStatus).toBe('in');       // an inbound line never carries a delivery tick

    expect((await alice.markRead(g.id)).ok).toBe(true);
    const after = (await alice.listConversations()).find((c) => c.id === g.id);
    expect(after.unread).toBe(0);
  });

  test('sending clears my own unread — you have seen a chat you just replied in', async () => {
    const g = await alice.createGroup({ name: 'תשובה', members: ['bob'] });
    await bob.sendMessage(g.id, { text: 'שאלה' });
    await alice.sendMessage(g.id, { text: 'תשובה' });
    const row = (await alice.listConversations()).find((c) => c.id === g.id);
    expect(row.unread).toBe(0);
    expect(row.lastDir).toBe('out');
  });

  test('a mention is scoped to the conversation and stored on the event', async () => {
    const g = await alice.createGroup({ name: 'אזכור', members: ['bob'] });
    const sent = await alice.sendMessage(g.id, { text: 'שאלה ל @bob בבקשה' });
    expect(sent.ok).toBe(true);
    const thread = await bob.getConversation(g.id);
    const msg = thread.messages.find((m) => m.id === sent.message.id);
    expect(msg.mentions).toContain('bob');
  });

  test('uploadMedia stages a blob that sendMessage attaches and a bot can download', async () => {
    const g = await alice.createGroup({ name: 'קובץ', members: ['bob'] });
    const bytes = Buffer.from('חשבונית לבדיקה', 'utf8');
    const up = await alice.uploadMedia({ fileName: 'חשבונית.txt', mimeType: 'text/plain', buffer: bytes });
    expect(up.ok).toBe(true);
    expect(up.sha256).toMatch(/^[0-9a-f]{64}$/);

    const sent = await alice.sendMessage(g.id, { text: '', attachment: up });
    expect(sent.ok).toBe(true);

    // the receive path the bot runtime uses — including the download() closure
    const env = await bob.inboundEnvelope(sent.message.id);
    expect(env.ok).toBe(true);
    expect(env.message.attachments).toHaveLength(1);
    const att = env.message.attachments[0];
    expect(att.name).toBe('חשבונית.txt');
    const back = await att.download();
    expect(Buffer.compare(back, bytes)).toBe(0);       // byte-identical
  });

  test('a bot-authored message is marked, so the receive path can refuse to answer it', async () => {
    const g = await alice.createGroup({ name: 'לולאה', members: ['bob'] });
    const human = await alice.sendMessage(g.id, { text: 'שלום' });
    const bot = await alice.sendMessage(g.id, { text: 'אני בוט', botId: 'hacohen-bot' });
    expect((await bob.inboundEnvelope(human.message.id)).botId).toBeNull();
    expect((await bob.inboundEnvelope(bot.message.id)).botId).toBe('hacohen-bot');
  });

  test('an unknown conversation is null, and an unknown send is notFound — never an outage', async () => {
    const missing = '00000000-0000-4000-8000-000000000000';
    expect(await alice.getConversation(missing)).toBeNull();
    const r = await alice.sendMessage(missing, { text: 'x' });
    expect(r.ok).toBe(false);
    expect(r.notFound).toBe(true);
    expect(r.reachable).toBeUndefined();     // the relay answered; this is not a degradation
  });

  test('a message needs text or an attachment', async () => {
    const g = await alice.createGroup({ name: 'ריק', members: [] });
    const r = await alice.sendMessage(g.id, { text: '   ' });
    expect(r.ok).toBe(false);
    expect(r.message).toBeNull();
  });

  test('subscribe delivers inbound ids in the shape local_inbox.js dispatches on', async () => {
    const g = await alice.createGroup({ name: 'דחיפה', members: ['bob'] });
    const seen = [];
    const un = await bob.subscribe((e) => seen.push(e));
    try {
      await new Promise((r) => setTimeout(r, 500));
      const sent = await alice.sendMessage(g.id, { text: 'דחוף' });
      await new Promise((r) => setTimeout(r, 2500));
      const hit = seen.find((e) => e.message_id === sent.message.id);
      expect(hit).toBeTruthy();
      expect(hit.kind).toBe('message');
      expect(hit.conversation_id).toBe(g.id);
      expect(hit.fromMe).toBe(false);        // it is alice's message, seen by bob
    } finally { await un(); }
  });
});

describe('BuzzChatBackend construction', () => {
  test('refuses to exist without the profile it acts as', () => {
    expect(() => new BuzzChatBackend({ nsec: mintIdentity().nsec }))
      .toThrow(/selfId/);
  });

  test('refuses to exist without a relay identity — there is no ambient one', () => {
    expect(() => new BuzzChatBackend({ selfId: 'admin' }))
      .toThrow(/nsec/);
  });

  test('does NOT advertise reconnect — absence is how a backend says "unsupported"', () => {
    const b = new BuzzChatBackend({ selfId: 'admin', nsec: mintIdentity().nsec });
    expect(typeof b.reconnect).toBe('undefined');
    // …while every canonical op IS there
    for (const op of ['listConversations', 'getConversation', 'sendMessage', 'markRead', 'probe']) {
      expect(typeof b[op]).toBe('function');
    }
  });
});
