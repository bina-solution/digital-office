/**
 * The private engine's receive path — who a message is inbound FOR, and who answers it.
 *
 * Driven through handleEvent with a stub resolver and a stub runtime, because the decisions under
 * test are entirely about routing: nothing here touches Postgres, and standing one up would test the
 * database rather than the rule.
 *
 * Both rules exist because breaking either is silent. Dispatching to the sender makes a bot answer
 * itself, and since every reply is another message it does so until something falls over. Dispatching
 * with the wrong backend makes the answer arrive from the operator instead of from the bot's own
 * identity, which looks like the admin talking to themselves.
 */
const inbox = require('../chatapi/local_inbox');

const ADMIN = 'admin';
const BOT_USER = 'bot-user';

/**
 * profile id -> vault instance id.
 *
 * The mapping is a LOOKUP now, not string concatenation. A private profile is an ordinary vault
 * instance (`chat_local-<8hex>`), so its id says nothing about who it is — which is exactly why an
 * identity can no longer be addressed by anyone who can spell one.
 */
const INST = {
  [ADMIN]: 'chat_local-a1a1a1a1',
  [BOT_USER]: 'chat_local-b2b2b2b2',
  b1: 'chat_local-c3c3c3c3',
  b2: 'chat_local-d4d4d4d4',
  broken: 'chat_local-e5e5e5e5',
};
const inst = (id) => INST[id];

/** The profile store, stubbed: only PROFILES are dispatchable, and a plain contact has no instance. */
const store = {
  get: async (id) => (INST[id]
    ? { id, display_name: id, status: 'active', instance_id: INST[id], is_admin: id === ADMIN }
    : null),
  firstAdmin: async () => ({ id: ADMIN, display_name: ADMIN, status: 'active', instance_id: INST[ADMIN], is_admin: true }),
};

/** An envelope as a backend's inboundEnvelope returns it — the shape is the CONTRACT, which is
 *  why this test survived the engine swap unchanged: adapters/buzz.js builds the same one. */
function envelope({ sender = ADMIN, members = [ADMIN, BOT_USER], text = 'שלום' } = {}) {
  return {
    ok: true,
    members,
    message: {
      id: 'msg-1', conversationId: 'dm-1', isGroup: members.length > 2, fromMe: false,
      sender: { id: sender, name: sender }, text, timestamp: new Date(), attachments: [], raw: {},
    },
  };
}

/** resolve() that hands back a distinct marker per connection id, so we can see WHICH was used. */
function resolver(env) {
  return async (cid) => ({
    cid,
    backend: { marker: cid, inboundEnvelope: async () => env },
  });
}

function runtimeWith(attachments) {
  const calls = [];
  return {
    calls,
    NO_BOT: { id: 'none' },
    attachedTo: (cid) => attachments[cid] || 'none',
    dispatch: async (msg, opts) => {
      calls.push({ msg, connectionId: opts.connectionId, backendMarker: opts.backend.marker });
      return { handled: true, reason: 'ok' };
    },
  };
}

test('a message is inbound for the OTHER participant, never the sender', async () => {
  // Both identities have the same bot attached. Only the non-sender may be dispatched to.
  const runtime = runtimeWith({
    [inst(ADMIN)]: 'hacohen-bot',
    [inst(BOT_USER)]: 'hacohen-bot',
  });
  const r = await inbox.handleEvent(
    { kind: 'message', message_id: 'msg-1' },
    { store, resolve: resolver(envelope({ sender: ADMIN })), runtime },
  );
  expect(runtime.calls).toHaveLength(1);
  expect(r.dispatched.map((d) => d.connectionId)).toEqual([inst(BOT_USER)]);
});

test('the bot answers AS its own identity, not as whoever is selected', async () => {
  const runtime = runtimeWith({ [inst(BOT_USER)]: 'hacohen-bot' });
  await inbox.handleEvent(
    { kind: 'message', message_id: 'msg-1' },
    { store, resolve: resolver(envelope()), runtime },
  );
  // The backend handed to the bot must be the one resolved for bot-user's connection.
  expect(runtime.calls[0].backendMarker).toBe(inst(BOT_USER));
  expect(runtime.calls[0].msg.fromMe).toBe(false);
});

test('an identity with no bot stays silent', async () => {
  const runtime = runtimeWith({});
  const r = await inbox.handleEvent(
    { kind: 'message', message_id: 'msg-1' },
    { store, resolve: resolver(envelope()), runtime },
  );
  expect(runtime.calls).toHaveLength(0);
  expect(r.dispatched).toEqual([]);
});

test('a group message reaches every other member that has a bot', async () => {
  const runtime = runtimeWith({
    [inst('b1')]: 'hacohen-bot',
    [inst('b2')]: 'hacohen-bot',
  });
  await inbox.handleEvent(
    { kind: 'message', message_id: 'msg-1' },
    { store, resolve: resolver(envelope({ sender: ADMIN, members: [ADMIN, 'b1', 'b2'] })), runtime },
  );
  expect(runtime.calls.map((c) => c.connectionId).sort())
    .toEqual([inst('b1'), inst('b2')].sort());
});

test('an event that is not a message is ignored', async () => {
  const runtime = runtimeWith({ [inst(BOT_USER)]: 'hacohen-bot' });
  expect(await inbox.handleEvent({ kind: 'typing' }, { store, resolve: resolver(envelope()), runtime }))
    .toEqual({ dispatched: [] });
  expect(await inbox.handleEvent(null, { store, resolve: resolver(envelope()), runtime }))
    .toEqual({ dispatched: [] });
  expect(runtime.calls).toHaveLength(0);
});

test('a message that cannot be read reports why instead of throwing', async () => {
  const runtime = runtimeWith({ [inst(BOT_USER)]: 'hacohen-bot' });
  const r = await inbox.handleEvent(
    { kind: 'message', message_id: 'gone' },
    { store, resolve: resolver({ ok: false, error: 'no such message' }), runtime },
  );
  expect(r).toMatchObject({ dispatched: [], reason: 'no such message' });
});

test('one unresolvable identity does not stop the others being answered', async () => {
  const runtime = runtimeWith({
    [inst('broken')]: 'hacohen-bot',
    [inst(BOT_USER)]: 'hacohen-bot',
  });
  const env = envelope({ sender: ADMIN, members: [ADMIN, 'broken', BOT_USER] });
  const resolve = async (cid) => {
    if (cid === inst('broken')) throw new Error('vault says no');
    return { cid, backend: { marker: cid, inboundEnvelope: async () => env } };
  };
  const r = await inbox.handleEvent({ kind: 'message', message_id: 'msg-1' }, { store, resolve, runtime });
  expect(r.dispatched.map((d) => d.connectionId)).toEqual([inst(BOT_USER)]);
});

test('a BOT-produced message never triggers another bot', async () => {
  // The loop that actually happened: the default operator inherits a bot from DEFAULT_ATTACHMENTS,
  // so as soon as a second bot-bearing identity existed the two answered each other without end —
  // every reply is a new message, which is a new inbound event, which earns another reply.
  const runtime = runtimeWith({
    [inst(ADMIN)]: 'hacohen-bot',
    [inst(BOT_USER)]: 'hacohen-bot',
  });
  const env = { ...envelope({ sender: BOT_USER }), botId: 'hacohen-bot' };
  const r = await inbox.handleEvent(
    { kind: 'message', message_id: 'msg-1' },
    { store, resolve: resolver(env), runtime },
  );
  expect(runtime.calls).toHaveLength(0);
  expect(r).toMatchObject({ dispatched: [], reason: 'produced by bot hacohen-bot' });
});

test('a PERSON acting as an identity that has a bot is still dispatched on', async () => {
  // The reason the guard reads the message and not the sender: the admin has a bot attached by
  // default, and a sender-based rule would silence exactly the messages that must reach one.
  const runtime = runtimeWith({
    [inst(ADMIN)]: 'hacohen-bot',
    [inst(BOT_USER)]: 'hacohen-bot',
  });
  const r = await inbox.handleEvent(
    { kind: 'message', message_id: 'msg-1' },
    { store, resolve: resolver({ ...envelope({ sender: ADMIN }), botId: null }), runtime },
  );
  expect(r.dispatched.map((d) => d.connectionId)).toEqual([inst(BOT_USER)]);
});
