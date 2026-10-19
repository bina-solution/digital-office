/**
 * The chat service's abstract HTTP surface — the routes added when the /admin dashboard was folded
 * back into the app: the connect catalogue, add/remove/probe a connection, broadcast, and export.
 *
 * Driven through a REAL express app with supertest rather than by calling handlers directly, because
 * three of the things being asserted are properties of the routing, not of the handler body: the
 * status code (207 for a partial fan-out), the Content-Disposition/Content-Type of a download, and
 * that DELETE /api/account/:id does not get swallowed by one of the POST /api/account/* routes.
 *
 * The adapter and the vault client are seams, not subjects — they have their own tests. What is
 * pinned here is what the routing layer decides on top of them, and every one of those decisions is
 * a rule that would otherwise rot in a comment.
 */
jest.mock('../chatapi/adapters', () => {
  const actual = jest.requireActual('../chatapi/adapters');
  // Spread, so AdapterError stays the SAME class object — server.js branches on `instanceof`, and a
  // re-created class would make every one of those branches silently take the 500 path.
  return { ...actual, resolveActive: jest.fn(), forget: jest.fn(async () => {}) };
});
jest.mock('../chatapi/connections_client', () => {
  const actual = jest.requireActual('../chatapi/connections_client');
  return {
    ...actual,
    listInstances: jest.fn(async () => ({ instances: [], reachable: true })),
    active: jest.fn(async () => null),
    select: jest.fn(async () => null),
    createInstance: jest.fn(async () => ({ id: 'new-id' })),
    deleteInstance: jest.fn(async () => ({ ok: true })),
  };
});
jest.mock('../bots/chat_bot', () => ({
  listBots: () => [{ id: 'none', name: 'ללא בוט', desc: '' }],
  attachedTo: () => 'none',
  attach: async () => 'none',
  getBot: jest.fn(() => null),
  settingsSchema: () => [],
  getSettings: () => ({}),
  setSettings: () => ({ ok: true, settings: {} }),
  clearSettings: jest.fn(() => ({ ok: true, cleared: [], settings: {} })),
}));

const express = require('express');
const request = require('supertest');

const adapters = require('../chatapi/adapters');
const cc = require('../chatapi/connections_client');
const server = require('../chatapi/server');

/** A backend stub that answers only the ops a test needs — the same way a real one advertises
 *  itself, so a route that assumes a method it never checked for fails here. */
function backend(over = {}) {
  return {
    listConversations: async () => [],
    getConversation: async () => null,
    sendMessage: async () => ({ ok: true }),
    markRead: async () => ({ ok: true }),
    probe: async () => ({ ok: true }),
    ...over,
  };
}

/**
 * The profile store, stubbed.
 *
 * `admin` is an admin profile whose vault instance is chat_local-a1a1a1a1; `user2` is an ordinary
 * one on chat_local-b2b2b2b2. Keys are what the rings resolve against — this is the whole point of
 * the change, so the routing tests hold a real credential rather than assuming an identity.
 */
const PROFILES = {
  admin: { id: 'admin', display_name: 'מנהל', is_admin: true, status: 'active', instance_id: 'chat_local-a1a1a1a1', key_fp: 'fp-admin' },
  user2: { id: 'user2', display_name: 'משתמש 2', is_admin: false, status: 'active', instance_id: 'chat_local-b2b2b2b2', key_fp: 'fp-user2' },
};
const KEYS = { 'chatp_admin': PROFILES.admin, 'chatp_user2': PROFILES.user2 };
const profileStore = {
  list: async () => Object.values(PROFILES),
  get: async (id) => PROFILES[id] || null,
  byKey: async (k) => KEYS[k] || null,
  byInstance: async (iid) => Object.values(PROFILES).find((p) => p.instance_id === iid) || null,
  firstAdmin: async () => PROFILES.admin,
};

function app(be = backend(), cid = 'chat_local-a1a1a1a1') {
  adapters.resolveActive.mockImplementation(async (explicit) => ({ cid: explicit || cid, backend: be }));
  const a = express();
  a.use(express.json());
  server.register(a, null, { profiles: profileStore });
  return a;
}

beforeEach(() => {
  jest.clearAllMocks();
  cc.listInstances.mockResolvedValue({ instances: [], reachable: true });
  cc.active.mockResolvedValue(null);
  cc.createInstance.mockResolvedValue({ id: 'new-id' });
  cc.deleteInstance.mockResolvedValue({ ok: true });
});

// ── the connect catalogue ────────────────────────────────────────────────────
describe('GET /api/chat-providers', () => {
  test('offers exactly the protocols the adapter layer can build — no more', async () => {
    // The sim's mock invented messenger + whatsapp_cloud. Offering a provider this service cannot
    // resolve is a button whose only possible outcome is a failure the operator reads as an outage.
    const r = await request(app()).get('/api/chat-providers');
    expect(r.status).toBe(200);
    const protocols = r.body.providers.flatMap((p) => p.auth_methods.map((m) => m.protocol));
    expect(protocols.sort()).toEqual([...cc.PROTOCOLS].sort());
    expect(r.body.providers.map((p) => p.id)).toEqual(['local', 'whatsapp', 'telegram']);
  });

  test('local is builtin and first — a fresh install is never shown an empty catalogue', async () => {
    const r = await request(app()).get('/api/chat-providers');
    expect(r.body.providers[0]).toMatchObject({ id: 'local', builtin: true });
  });

  test('`direct` separates a credential you can type from a pairing ceremony', async () => {
    const r = await request(app()).get('/api/chat-providers');
    const by = Object.fromEntries(r.body.providers.map((p) => [p.id, p]));
    expect(by.telegram.auth_methods[0]).toMatchObject({ direct: true, needs: ['token'] });
    expect(by.whatsapp.auth_methods[0].direct).toBe(false);   // QR lives in the console
  });
});

// ── add a connection ─────────────────────────────────────────────────────────
describe('POST /api/account/add', () => {
  test('protocol and label are both required', async () => {
    const r = await request(app()).post('/api/account/add').send({ protocol: 'chat_tg_bot' });
    expect(r.status).toBe(400);
    expect(cc.createInstance).not.toHaveBeenCalled();
  });

  test('an unsupported protocol is refused WITH the supported list', async () => {
    const r = await request(app()).post('/api/account/add').send({ protocol: 'chat_signal', label: 'x' });
    expect(r.status).toBe(400);
    expect(r.body.supported).toEqual(cc.PROTOCOLS);
  });

  test('the built-in local chat cannot be added a second time', async () => {
    // It is synthetic: no vault row, no distinct backend. A second one would resolve to the first.
    const r = await request(app()).post('/api/account/add').send({ protocol: 'chat_local', label: 'x' });
    expect(r.status).toBe(400);
    expect(cc.createInstance).not.toHaveBeenCalled();
  });

  test('a QR-paired protocol is refused HERE and names where it is done', async () => {
    const r = await request(app()).post('/api/account/add').send({ protocol: 'chat_wa_baileys', label: 'עסקי' });
    expect(r.status).toBe(400);
    expect(r.body.error).toMatch(/חיבורים ומפתחות/);
    expect(cc.createInstance).not.toHaveBeenCalled();
  });

  test('a typed credential is FORWARDED to the vault verbatim and answers 201', async () => {
    cc.createInstance.mockResolvedValue({ id: 'chat_tg_bot-abcd1234' });
    const r = await request(app()).post('/api/account/add')
      .send({ protocol: 'chat_tg_bot', label: 'טלגרם', secret: { token: '123:ABC' }, account_hint: '@bot' });
    expect(r.status).toBe(201);
    expect(r.body).toMatchObject({ ok: true, id: 'chat_tg_bot-abcd1234' });
    expect(cc.createInstance).toHaveBeenCalledWith('chat_tg_bot', 'טלגרם', { token: '123:ABC' }, '@bot');
  });

  test('a vault error keeps its own status; an unreachable vault (0) becomes 502', async () => {
    cc.createInstance.mockRejectedValue(new cc.ConnectionsError('connections 400 for /api/instances', 400));
    expect((await request(app()).post('/api/account/add')
      .send({ protocol: 'chat_tg_bot', label: 'x', secret: { token: 't' } })).status).toBe(400);

    cc.createInstance.mockRejectedValue(new cc.ConnectionsError('connections unreachable', 0));
    const r = await request(app()).post('/api/account/add')
      .send({ protocol: 'chat_tg_bot', label: 'x', secret: { token: 't' } });
    // 0 is not a status a client can act on — the caller must be able to tell "upstream is down".
    expect(r.status).toBe(502);
  });
});

// ── remove a connection ──────────────────────────────────────────────────────
describe('DELETE /api/account/:id', () => {
  test('the synthetic local connection cannot be removed', async () => {
    // Removing it would break the zero-config guarantee: a fresh install always has one that works.
    const r = await request(app()).delete('/api/account/chat_local-a1a1a1a1');
    expect(r.status).toBe(400);
    expect(cc.deleteInstance).not.toHaveBeenCalled();
  });

  test('deleting the ACTIVE connection clears the pointer', async () => {
    // Otherwise the pointer dangles at a dead id and every op answers 503 for an account the
    // operator believes they removed — /readyz would report "not ready" with no way back.
    cc.active.mockResolvedValue('chat_tg_bot-dead');
    const r = await request(app()).delete('/api/account/chat_tg_bot-dead');
    expect(r.status).toBe(200);
    expect(cc.select).toHaveBeenCalledWith(null);
    expect(adapters.forget).toHaveBeenCalledWith('chat_tg_bot-dead');
  });

  test('deleting a NON-active connection leaves the pointer alone', async () => {
    cc.active.mockResolvedValue('chat_local-a1a1a1a1');
    await request(app()).delete('/api/account/chat_tg_bot-other');
    expect(cc.select).not.toHaveBeenCalled();
    expect(adapters.forget).toHaveBeenCalledWith('chat_tg_bot-other');
  });

  test('an unknown id keeps the vault 404 rather than becoming a 500', async () => {
    cc.deleteInstance.mockRejectedValue(new cc.ConnectionsError('not found', 404));
    const r = await request(app()).delete('/api/account/nope');
    expect(r.status).toBe(404);
    expect(adapters.forget).not.toHaveBeenCalled();     // nothing was removed — nothing to forget
  });
});

// ── reset per-connection bot settings ────────────────────────────────────────
describe('DELETE /api/bots/:id/settings', () => {
  const bots = require('../bots/chat_bot');

  test('resets the whole pair on the ACTIVE connection when none is named', async () => {
    bots.getBot.mockReturnValue({ id: 'b1' });
    bots.clearSettings.mockReturnValue({ ok: true, cleared: ['greeting'], settings: { greeting: 'shalom' } });
    cc.active.mockResolvedValue('chat_tg_bot-1');
    const r = await request(app()).delete('/api/bots/b1/settings');
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ ok: true, connection_id: 'chat_tg_bot-1', cleared: ['greeting'] });
    expect(bots.clearSettings).toHaveBeenCalledWith('chat_tg_bot-1', 'b1', null);
  });

  test('a key list is passed through, so one field can be reset alone', async () => {
    bots.getBot.mockReturnValue({ id: 'b1' });
    bots.clearSettings.mockReturnValue({ ok: true, cleared: ['cap'], settings: {} });
    await request(app()).delete('/api/bots/b1/settings').send({ connection_id: 'c9', keys: ['cap'] });
    expect(bots.clearSettings).toHaveBeenCalledWith('c9', 'b1', ['cap']);
  });

  test('an unknown BOT is a 404; a bad key on a real bot is a 400', async () => {
    // The distinction the panel needs: one means "that bot is gone", the other "fix your input".
    bots.getBot.mockReturnValue(null);
    bots.clearSettings.mockReturnValue({ ok: false, error: 'unknown bot "ghost"' });
    expect((await request(app()).delete('/api/bots/ghost/settings')).status).toBe(404);

    bots.getBot.mockReturnValue({ id: 'b1' });
    bots.clearSettings.mockReturnValue({ ok: false, error: 'unknown setting "typo"' });
    const r = await request(app()).delete('/api/bots/b1/settings').send({ keys: ['typo'] });
    expect(r.status).toBe(400);
    expect(r.body.error).toMatch(/unknown setting/);
  });
});

// ── probe one connection ─────────────────────────────────────────────────────
describe('GET /api/account/:id/probe', () => {
  test('unknown connection is a 404, not a probe of something else', async () => {
    const r = await request(app()).get('/api/account/ghost/probe');
    expect(r.status).toBe(404);
  });

  test('a healthy connection reports ok with its identity', async () => {
    cc.listInstances.mockResolvedValue({
      instances: [{ id: 'chat_tg_bot-1', protocol: 'chat_tg_bot', account_hint: '@bot' }], reachable: true });
    const r = await request(app(backend({ probe: async () => ({ ok: true }) }))).get('/api/account/chat_tg_bot-1/probe');
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ ok: true, id: 'chat_tg_bot-1', identity: '@bot', protocol: 'chat_tg_bot' });
  });

  test('an UNHEALTHY connection is still a 200 — the question was answered', async () => {
    // Forwarding the backend's 503 would make an operator's health check read as an outage of this
    // route, and the connect flow could not tell "I could not ask" from "the answer is no".
    cc.listInstances.mockResolvedValue({ instances: [{ id: 'c1', protocol: 'chat_tg_bot' }], reachable: true });
    const r = await request(app(backend({ probe: async () => ({ ok: false, error: '401 Unauthorized' }) })))
      .get('/api/account/c1/probe');
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ ok: false, reason: '401 Unauthorized' });
  });

  test('a connection that cannot be RESOLVED reports ok:false with the adapter reason', async () => {
    cc.listInstances.mockResolvedValue({ instances: [{ id: 'c1', protocol: 'chat_tg_bot' }], reachable: true });
    const a = express(); a.use(express.json());
    adapters.resolveActive.mockRejectedValue(new adapters.AdapterError('secret needs {token}', 502, 'c1'));
    server.register(a, null, { profiles: profileStore });
    const r = await request(a).get('/api/account/c1/probe');
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ ok: false, reason: 'secret needs {token}', id: 'c1' });
  });

  test('probes the connection NAMED, never the active one', async () => {
    cc.listInstances.mockResolvedValue({ instances: [{ id: 'c9', protocol: 'chat_tg_bot' }], reachable: true });
    await request(app(backend(), 'chat_local-a1a1a1a1')).get('/api/account/c9/probe');
    expect(adapters.resolveActive).toHaveBeenCalledWith('c9');
  });
});

// ── broadcast ────────────────────────────────────────────────────────────────
describe('POST /api/broadcast', () => {
  test('empty text is refused before any send', async () => {
    const send = jest.fn();
    const r = await request(app(backend({ sendMessage: send }))).post('/api/broadcast').send({ text: '  ' });
    expect(r.status).toBe(400);
    expect(send).not.toHaveBeenCalled();
  });

  test('an unqualified broadcast does NOT default to everyone', async () => {
    // The one mistake here that cannot be taken back. `to:"all"` has to be typed.
    const send = jest.fn();
    const be = backend({ sendMessage: send, listConversations: async () => [{ id: 'a' }, { id: 'b' }] });
    const r = await request(app(be)).post('/api/broadcast').send({ text: 'שלום' });
    expect(r.status).toBe(400);
    expect(send).not.toHaveBeenCalled();
  });

  test('to:"all" fans out over the backend\'s own conversation list', async () => {
    const send = jest.fn(async () => ({ ok: true }));
    const be = backend({ sendMessage: send, listConversations: async () => [{ id: 'a' }, { id: 'b' }] });
    const r = await request(app(be)).post('/api/broadcast').send({ text: 'שלום', to: 'all' });
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ ok: true, sent: 2, failed: 0 });
    expect(send.mock.calls.map((c) => c[0])).toEqual(['a', 'b']);
  });

  test('explicit conversation_ids win over the list', async () => {
    const list = jest.fn(async () => [{ id: 'a' }]);
    const send = jest.fn(async () => ({ ok: true }));
    const r = await request(app(backend({ sendMessage: send, listConversations: list })))
      .post('/api/broadcast').send({ text: 'x', conversation_ids: ['z'] });
    expect(r.status).toBe(200);
    expect(list).not.toHaveBeenCalled();
    expect(send).toHaveBeenCalledWith('z', { text: 'x' });
  });

  test('a PARTIAL fan-out is a 207 and names which recipients failed', async () => {
    // 200 would be a lie for a half-delivered broadcast; 500 would be a lie for one bad recipient
    // out of forty. Either way the operator cannot find out which five never went.
    const send = jest.fn(async (id) => (id === 'b' ? { ok: false, error: 'blocked' } : { ok: true }));
    const r = await request(app(backend({ sendMessage: send })))
      .post('/api/broadcast').send({ text: 'x', conversation_ids: ['a', 'b', 'c'] });
    expect(r.status).toBe(207);
    expect(r.body).toMatchObject({ ok: false, sent: 2, failed: 1 });
    expect(r.body.results.filter((x) => !x.ok)).toEqual([{ id: 'b', ok: false, error: 'blocked' }]);
  });

  test('a throwing recipient does not abort the rest of the fan-out', async () => {
    const send = jest.fn(async (id) => { if (id === 'a') throw new Error('socket gone'); return { ok: true }; });
    const r = await request(app(backend({ sendMessage: send })))
      .post('/api/broadcast').send({ text: 'x', conversation_ids: ['a', 'b'] });
    expect(r.status).toBe(207);
    expect(r.body).toMatchObject({ sent: 1, failed: 1 });
  });

  test('honours a per-call connection_id', async () => {
    await request(app()).post('/api/broadcast').send({ text: 'x', conversation_ids: ['a'], connection_id: 'other' });
    expect(adapters.resolveActive).toHaveBeenCalledWith('other');
  });

  test('an unresolvable connection is a CONFIG fault, not a 500', async () => {
    const a = express(); a.use(express.json());
    adapters.resolveActive.mockRejectedValue(new adapters.AdapterError('gone', 503, 'c1'));
    server.register(a, null, { profiles: profileStore });
    const r = await request(a).post('/api/broadcast').send({ text: 'x', conversation_ids: ['a'] });
    expect(r.status).toBe(503);
    expect(r.body).toMatchObject({ error: 'gone', connection_id: 'c1' });
  });
});

// ── chat export ──────────────────────────────────────────────────────────────
describe('GET /api/export/conversations', () => {
  const CONVS = [{ id: 'c1', name: 'משה', handle: '+972', group: false }];
  const THREAD = {
    id: 'c1',
    contact: { name: 'משה', handle: '+972', group: false, tag: 'לקוח' },
    messages: [
      { id: 'm1', dir: 'in', text: 'שלום', mins: 60, status: 'in' },
      { id: 'm2', dir: 'out', text: 'היי', mins: 30, status: 'read' },
    ],
  };
  const exporter = (over = {}) => backend({
    listConversations: async () => CONVS,
    getConversation: async () => THREAD,
    ...over,
  });

  test('uses ONLY canonical ops, so it works on every backend', async () => {
    // The whole point of replacing /api/wa-archive/*: that one reads the WhatsApp SQLite file and
    // can never answer for local chat or Telegram.
    const list = jest.fn(async () => CONVS);
    const get = jest.fn(async () => THREAD);
    const r = await request(app(exporter({ listConversations: list, getConversation: get })))
      .get('/api/export/conversations');
    expect(r.status).toBe(200);
    expect(list).toHaveBeenCalled();
    expect(get).toHaveBeenCalledWith('c1');
    expect(r.body).toMatchObject({ connection_id: 'chat_local-a1a1a1a1', messages: 2 });
    expect(r.body.conversations[0]).toMatchObject({ id: 'c1', name: 'משה', tag: 'לקוח' });
  });

  test('derives an absolute time from the contract\'s AGE, and names it as approximate', async () => {
    const r = await request(app(exporter())).get('/api/export/conversations');
    const m = r.body.conversations[0].messages[0];
    expect(m).toHaveProperty('at_approx');
    expect(Date.now() - Date.parse(m.at_approx)).toBeGreaterThan(59 * 60000);
    expect(Date.now() - Date.parse(m.at_approx)).toBeLessThan(62 * 60000);
  });

  test('downloads as a file, named for the connection', async () => {
    const r = await request(app(exporter())).get('/api/export/conversations');
    expect(r.headers['content-disposition']).toMatch(/attachment; filename="chat-export_chat_local-a1a1a1a1_.*\.json"/);
  });

  test('csv carries a BOM and the right content type', async () => {
    // Excel reads a BOM-less UTF-8 csv as the local codepage and every Hebrew name becomes mojibake,
    // which makes the export useless for exactly the people it is for.
    const r = await request(app(exporter())).get('/api/export/conversations?format=csv');
    expect(r.headers['content-type']).toMatch(/text\/csv/);
    expect(r.headers['content-disposition']).toMatch(/\.csv"/);
    expect(r.text.charCodeAt(0)).toBe(0xfeff);
    expect(r.text.slice(1).split('\r\n')[0]).toBe(
      'conversation_id,conversation,handle,group,message_id,direction,sender,text,at_approx,minutes_ago,status');
    expect(r.text.split('\r\n')).toHaveLength(4);           // header + 2 rows + trailing
  });

  test('csv neutralises a formula a CUSTOMER can type into the chat', async () => {
    const be = exporter({ getConversation: async () => ({
      ...THREAD, messages: [{ id: 'm1', dir: 'in', text: '=cmd|\' /c calc\'!A1', mins: 1, status: 'in' }] }) });
    const r = await request(app(be)).get('/api/export/conversations?format=csv');
    expect(r.text).toMatch(/,'=cmd/);                        // apostrophe-prefixed, so Excel shows it
    expect(r.text).not.toMatch(/,=cmd/);                     // …and never evaluates it
    // The same rule applies to a phone number: a leading + is a formula trigger in Excel too.
    expect(r.text).toMatch(/,'\+972,/);
  });

  test('csv quoting survives a comma, a quote and a newline in a message', async () => {
    const be = exporter({ getConversation: async () => ({
      ...THREAD, messages: [{ id: 'm1', dir: 'in', text: 'a,b "c"\nd', mins: 1, status: 'in' }] }) });
    const r = await request(app(be)).get('/api/export/conversations?format=csv');
    expect(r.text).toContain('"a,b ""c""\nd"');
  });

  test('an unsupported format is refused rather than silently defaulting', async () => {
    const r = await request(app(exporter())).get('/api/export/conversations?format=pdf');
    expect(r.status).toBe(400);
    expect(r.body.supported).toEqual(['json', 'csv']);
  });

  test('one conversation can be exported on its own, without listing', async () => {
    const list = jest.fn(async () => CONVS);
    const r = await request(app(exporter({ listConversations: list })))
      .get('/api/export/conversations?conversation_id=c1');
    expect(r.status).toBe(200);
    expect(list).not.toHaveBeenCalled();
    expect(r.body.conversations).toHaveLength(1);
  });

  test('a named conversation that does not exist is a 404', async () => {
    const r = await request(app(exporter({ getConversation: async () => null })))
      .get('/api/export/conversations?conversation_id=ghost');
    expect(r.status).toBe(404);
  });

  test('a conversation that vanishes mid-export is SKIPPED, not a 404 for the whole file', async () => {
    const be = exporter({
      listConversations: async () => [{ id: 'c1' }, { id: 'gone' }],
      getConversation: async (id) => (id === 'gone' ? null : THREAD),
    });
    const r = await request(app(be)).get('/api/export/conversations');
    expect(r.status).toBe(200);
    expect(r.body.conversations.map((c) => c.id)).toEqual(['c1']);
  });

  test('limit is clamped, so one request cannot ask for the whole archive', async () => {
    const many = Array.from({ length: 600 }, (_, i) => ({ id: `c${i}` }));
    const get = jest.fn(async () => THREAD);
    const r = await request(app(exporter({ listConversations: async () => many, getConversation: get })))
      .get('/api/export/conversations?limit=9999');
    expect(r.status).toBe(200);
    expect(get).toHaveBeenCalledTimes(500);
  });

  test('honours a per-call connection_id', async () => {
    await request(app(exporter())).get('/api/export/conversations?connection_id=other');
    expect(adapters.resolveActive).toHaveBeenCalledWith('other');
  });

  test('an unresolvable connection is a config fault carrying the connection id', async () => {
    const a = express(); a.use(express.json());
    adapters.resolveActive.mockRejectedValue(new adapters.AdapterError('החיבור אינו קיים', 503, 'c1'));
    server.register(a, null, { profiles: profileStore });
    const r = await request(a).get('/api/export/conversations');
    expect(r.status).toBe(503);
    expect(r.body).toMatchObject({ connection_id: 'c1' });
  });
});

// ── starting a conversation ──────────────────────────────────────────────────
describe('GET /api/users', () => {
  test('a backend that cannot enumerate its address book says 501, not an empty list', async () => {
    // "Nobody to talk to" and "this transport cannot tell you who you can talk to" are different
    // facts. An empty array states the first while meaning the second, and the UI would render a
    // "no contacts" screen for a WhatsApp account with thousands.
    const r = await request(app(backend())).get('/api/users');
    expect(r.status).toBe(501);
    expect(r.body.error).toMatch(/cannot list users/);
    expect(r.body.connection_id).toBe('chat_local-a1a1a1a1');
  });

  test('forwards the search term and limit to the backend', async () => {
    let got = null;
    const be = backend({ listUsers: async (a) => { got = a; return { ok: true, users: [] }; } });
    await request(app(be)).get('/api/users?q=משה&limit=5');
    expect(got).toMatchObject({ q: 'משה', limit: '5' });
  });

  test('honours a per-call connection_id like every other op', async () => {
    const be = backend({ listUsers: async () => ({ ok: true, users: [] }) });
    await request(app(be)).get('/api/users?connection_id=chat_tg_bot-abc');
    expect(adapters.resolveActive).toHaveBeenCalledWith('chat_tg_bot-abc');
  });
});

describe('POST /api/conversations', () => {
  test('a user_id opens a direct chat', async () => {
    let got = null;
    const be = backend({ createDirect: async (a) => { got = a; return { ok: true, id: 'dm-1', created: true }; } });
    const r = await request(app(be)).post('/api/conversations').send({ user_id: 'u-1', name: 'משה' });
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ ok: true, id: 'dm-1', created: true, connection_id: 'chat_local-a1a1a1a1' });
    expect(got).toMatchObject({ userId: 'u-1', name: 'משה' });
  });

  test('a title opens a group — one button, two shapes', async () => {
    let got = null;
    const be = backend({ createGroup: async (a) => { got = a; return { ok: true, id: 'grp-1' }; } });
    const r = await request(app(be)).post('/api/conversations').send({ title: 'ספקים', members: ['u-1'] });
    expect(r.status).toBe(200);
    expect(got).toMatchObject({ name: 'ספקים', members: ['u-1'] });
  });

  test('bad input from the backend is a 400, not a 500', async () => {
    // ok:false here means the operator asked for something impossible (a self-DM, a nameless
    // group). Reporting that as a server fault would send them looking for an outage.
    const be = backend({ createDirect: async () => ({ ok: false, error: 'cannot open a conversation with yourself' }) });
    const r = await request(app(be)).post('/api/conversations').send({ user_id: 'me' });
    expect(r.status).toBe(400);
    expect(r.body.error).toMatch(/yourself/);
  });

  test('a backend without the op says 501 and names which one', async () => {
    const r = await request(app(backend())).post('/api/conversations').send({ user_id: 'u-1' });
    expect(r.status).toBe(501);
    expect(r.body.error).toMatch(/createDirect/);
    const g = await request(app(backend())).post('/api/conversations').send({ title: 'x' });
    expect(g.status).toBe(501);
    expect(g.body.error).toMatch(/createGroup/);
  });
});

describe('POST /api/conversations — the shape is decided by user_id, not by name', () => {
  test('a peer display name does not turn a direct chat into a group', async () => {
    // `name` means the GROUP's name in one shape and the PEER's name in the other. Deciding on
    // `name` first routed "open a chat with משה" to createGroup, and BOTH calls succeed and return
    // a conversation id — so the operator gets a group called משה and nothing reports a problem.
    let direct = false;
    const be = backend({
      createDirect: async () => { direct = true; return { ok: true, id: 'dm-1' }; },
      createGroup: async () => ({ ok: true, id: 'grp-WRONG' }),
    });
    const r = await request(app(be)).post('/api/conversations').send({ user_id: 'u-1', name: 'משה' });
    expect(direct).toBe(true);
    expect(r.body.id).toBe('dm-1');
  });

  test('neither a user_id nor a title is bad input, not a 501', async () => {
    const be = backend({ createDirect: async () => ({ ok: true }), createGroup: async () => ({ ok: true }) });
    const r = await request(app(be)).post('/api/conversations').send({});
    expect(r.status).toBe(400);
    expect(r.body.error).toMatch(/user_id.*direct.*title.*group/);
  });
});

// ── platform-service.v1: the console's dialect ───────────────────────────────
describe('root-level aliases the console account chip calls', () => {
  test('GET /connections speaks the console field names, not the chat client ones', async () => {
    // The chip renders `account_hint`; the chat UI renders `identity`. Same value, two audiences.
    cc.listInstances.mockResolvedValue({
      instances: [{ id: 'chat_local-a1a1a1a1', protocol: 'chat_local', label: 'צ׳אט מקומי', identity: 'שירות פנימי', builtin: true }],
      reachable: true,
    });
    const r = await request(app()).get('/connections');
    expect(r.status).toBe(200);
    expect(r.body.connections[0]).toMatchObject({
      id: 'chat_local-a1a1a1a1', protocol: 'chat_local', label: 'צ׳אט מקומי', account_hint: 'שירות פנימי', status: 'ok',
    });
    expect(r.body.active).toBe('chat_local-a1a1a1a1');
  });

  test('/readyz and /manifest answer the same as their /api twins', async () => {
    // If these two ever disagree, the chip and the app report different health for one connection
    // and there is no way to tell which is lying.
    const be = backend({ probe: async () => ({ ok: true, protocol: 'chat_local' }) });
    const a = app(be);
    const [root, api] = await Promise.all([request(a).get('/readyz'), request(a).get('/api/readyz')]);
    expect(root.status).toBe(api.status);
    expect(root.body).toEqual(api.body);

    const [rm, am] = await Promise.all([request(a).get('/manifest'), request(a).get('/api/manifest')]);
    expect(rm.body).toEqual(am.body);
  });

  test('GET /providers is the SAME body as /api/chat-providers', async () => {
    const a = app();
    const [root, api] = await Promise.all([request(a).get('/providers'), request(a).get('/api/chat-providers')]);
    expect(root.body).toEqual(api.body);
  });

  test('POST /connections/select rejects an unknown id rather than pointing at nothing', async () => {
    cc.listInstances.mockResolvedValue({ instances: [{ id: 'chat_local-a1a1a1a1' }], reachable: true });
    const r = await request(app()).post('/connections/select').send({ id: 'nope' });
    expect(r.status).toBe(404);
  });

  test('DELETE /connections/:id refuses the built-in local connection', async () => {
    const r = await request(app()).delete('/connections/chat_local-a1a1a1a1');
    expect(r.status).toBe(400);
    expect(cc.deleteInstance).not.toHaveBeenCalled();
  });

  test('POST /connections refuses a protocol this service cannot build', async () => {
    // The vault would accept anything; offering a protocol the adapter cannot resolve creates a
    // connection that can only ever fail to probe.
    const r = await request(app()).post('/connections').send({ protocol: 'chat_messenger', label: 'x', secret: { t: 1 } });
    expect(r.status).toBe(400);
    expect(cc.createInstance).not.toHaveBeenCalled();
  });

  test('POST /connections refuses local — it is built in and holds no secret', async () => {
    const r = await request(app()).post('/connections').send({ protocol: 'chat_local', label: 'x' });
    expect(r.status).toBe(400);
    expect(cc.createInstance).not.toHaveBeenCalled();
  });
});

// ── live updates ─────────────────────────────────────────────────────────────
describe('GET /api/events (SSE)', () => {
  const http = require('http');

  /** Open a real socket — supertest buffers to completion, and a stream never completes. */
  function open(a, path = '/api/events') {
    return new Promise((resolve) => {
      const srv = http.createServer(a).listen(0, () => {
        const req = http.request({ port: srv.address().port, path, method: 'GET' }, (res) => {
          let buf = '';
          res.on('data', (d) => { buf += d; });
          resolve({ res, srv, req, body: () => buf, done: () => new Promise((r) => { req.destroy(); srv.close(r); }) });
        });
        req.end();
      });
    });
  }

  test('a backend that cannot push says 501, so the client knows to keep polling', async () => {
    const r = await request(app(backend())).get('/api/events');
    expect(r.status).toBe(501);
    expect(r.body.error).toMatch(/cannot push/);
  });

  test('opens a stream and announces itself before anything has happened', async () => {
    // Without the `ready` frame the client cannot tell "connected, nothing yet" from "still
    // connecting", and would sit behind a spinner on a perfectly healthy stream.
    const be = backend({ subscribe: async () => async () => {} });
    const c = await open(app(be));
    expect(c.res.statusCode).toBe(200);
    expect(c.res.headers['content-type']).toMatch(/text\/event-stream/);
    // proxies buffer a stream to death unless told not to
    expect(c.res.headers['x-accel-buffering']).toBe('no');
    await new Promise((r) => setTimeout(r, 50));
    expect(c.body()).toMatch(/event: ready/);
    await c.done();
  });

  test('a backend event reaches the wire as a change frame', async () => {
    let push = null;
    const be = backend({ subscribe: async (cb) => { push = cb; return async () => {}; } });
    const c = await open(app(be));
    await new Promise((r) => setTimeout(r, 50));
    push({ kind: 'message', conversation_id: 'c1', message_id: 'm1' });
    await new Promise((r) => setTimeout(r, 50));
    expect(c.body()).toMatch(/event: change/);
    expect(c.body()).toMatch(/"conversation_id":"c1"/);
    await c.done();
  });

  test('the subscription is released when the client disconnects', async () => {
    // Each dropped browser tab otherwise leaks a dedicated LISTEN client. It is invisible until the
    // database refuses new connections hours later, which reads as a database fault, not a leak.
    let released = 0;
    const be = backend({ subscribe: async () => async () => { released += 1; } });
    const c = await open(app(be));
    await new Promise((r) => setTimeout(r, 50));
    await c.done();
    await new Promise((r) => setTimeout(r, 100));
    expect(released).toBe(1);
  });
});
