/**
 * The TELEGRAM backend's projection, its op surface and its degradation — tested without a network.
 *
 * Same reasoning as tests/local_chat_backend.test.js and tests/baileys_backend.test.js: the client
 * renders a field it cannot find as EMPTY rather than as an error, so the field mapping is both the
 * most likely thing to be wrong and the least visible when it is.
 *
 * `fetch` is injected through the constructor's `deps` seam. Beyond the usual "tests should not need
 * a network", that seam is what lets these tests assert the ONE thing about this backend that is
 * genuinely dangerous to get wrong: that `getUpdates` is never called with an `offset`. An offset
 * CONFIRMS updates, and a confirmed update is deleted from Telegram's queue — a list refresh that
 * quietly consumed the queue would make the bot's own poller miss real customer messages.
 */
const {
  TelegramBackend,
  conversationFrom, messageFrom, sortConversations,
  minsAgoUnix, chatName, chatHandle, senderName, textOf, messageOf, isGroupChat,
  degradedList, TelegramApiError,
} = require('../chatapi/adapters/telegram');

const TOKEN = '123456:TEST-TOKEN';
/** Telegram dates are UNIX seconds. */
const unix = (mins) => Math.floor((Date.now() - mins * 60000) / 1000);

const PRIVATE = { id: 4242, type: 'private', first_name: 'משה', last_name: 'כהן', username: 'moshe' };
const GROUP = { id: -1001234, type: 'supergroup', title: 'צוות הלשכה' };
const FROM = { id: 4242, is_bot: false, first_name: 'משה', last_name: 'כהן' };

const upd = (id, chat, from, text, mins, extra = {}) => ({
  update_id: id * 10,
  message: { message_id: id, chat, from, text, date: unix(mins), ...extra },
});

describe('minsAgoUnix', () => {
  test('converts UNIX seconds to minutes ago', () => {
    expect(minsAgoUnix(unix(26))).toBe(26);
  });
  test('null for a missing date rather than a bogus 0', () => {
    expect(minsAgoUnix(0)).toBeNull();
    expect(minsAgoUnix(null)).toBeNull();
    expect(minsAgoUnix('nope')).toBeNull();
  });
  test('never negative when the clock is slightly behind Telegram\'s', () => {
    expect(minsAgoUnix(Math.floor(Date.now() / 1000) + 60)).toBe(0);
  });
});

describe('naming', () => {
  test('a person is their full name; a group is its title', () => {
    expect(chatName(PRIVATE)).toBe('משה כהן');
    expect(chatName(GROUP)).toBe('צוות הלשכה');
  });
  test('a chat with nothing but a username is named by it', () => {
    expect(chatName({ id: 9, type: 'private', username: 'BinaOfficeBot' })).toBe('@BinaOfficeBot');
  });
  test('the handle is the @username when there is one', () => {
    expect(chatHandle(PRIVATE)).toBe('@moshe');
  });
  test('a group with no username says what it IS — a bot cannot count members for free', () => {
    expect(chatHandle(GROUP)).toBe('קבוצה');
    expect(chatHandle({ id: -1, type: 'channel' })).toBe('ערוץ');
  });
  test('a private chat with no username falls back to the id, never to a blank subtitle', () => {
    expect(chatHandle({ id: 77, type: 'private' })).toBe('#77');
  });
  test('a group bubble is attributed to the SENDER, which in a group is not the chat', () => {
    expect(senderName(FROM)).toBe('משה כהן');
    expect(senderName({ id: 5, username: 'rachel' })).toBe('@rachel');
  });
});

describe('textOf', () => {
  test('text wins, then caption', () => {
    expect(textOf({ text: 'שלום' })).toBe('שלום');
    expect(textOf({ caption: 'כיתוב' })).toBe('כיתוב');
  });
  test('an attachment-only message still previews as something', () => {
    // an empty list row is a conversation the operator cannot see has activity
    expect(textOf({ document: { file_name: 'inv.pdf' } })).toBe('📎 inv.pdf');
    expect(textOf({ photo: [{ file_id: 'x' }] })).toBe('📎 תמונה');
    expect(textOf({ voice: { duration: 3 } })).toBe('📎 הודעה קולית');
  });
  test('nothing at all is an empty string, not undefined', () => {
    expect(textOf({})).toBe('');
    expect(textOf(null)).toBe('');
  });
});

describe('messageOf', () => {
  test('finds the payload in all four update shapes a chat can arrive in', () => {
    const m = { message_id: 1 };
    expect(messageOf({ message: m })).toBe(m);
    expect(messageOf({ edited_message: m })).toBe(m);
    expect(messageOf({ channel_post: m })).toBe(m);
    expect(messageOf({ edited_channel_post: m })).toBe(m);
  });
  test('an update that is not a message at all is ignored, not crashed on', () => {
    expect(messageOf({ callback_query: {} })).toBeNull();
    expect(messageOf(null)).toBeNull();
  });
});

describe('conversationFrom / messageFrom', () => {
  const entry = {
    chat: PRIVATE,
    unread: 2,
    readAt: 0,
    messages: [
      { id: 1, dir: 'in', text: 'שלום', date: unix(60), senderId: 4242, senderName: 'משה כהן' },
      { id: 2, dir: 'out', text: 'בטח!', date: unix(12), senderId: null, senderName: '' },
    ],
  };

  test('every field the client reads is present — an absent one renders empty, silently', () => {
    const c = conversationFrom(entry);
    for (const k of ['id', 'name', 'handle', 'initials', 'color', 'tag', 'group', 'unread',
      'pinned', 'online', 'typing', 'lastDir', 'lastStatus', 'last', 'mins']) {
      expect(c).toHaveProperty(k);
    }
  });

  test('the id is a STRING — it is a URL path segment and a Map key', () => {
    expect(conversationFrom(entry).id).toBe('4242');
  });

  test('the last message drives the preview, the direction and the age', () => {
    expect(conversationFrom(entry)).toMatchObject({
      name: 'משה כהן', handle: '@moshe', group: false, tag: '', unread: 2,
      lastDir: 'out', lastStatus: 'sent', last: 'בטח!', mins: 12,
    });
  });

  test('an inbound last message is lastStatus:in — a direction, not a delivery state', () => {
    const c = conversationFrom({ ...entry, messages: [entry.messages[0]] });
    expect(c.lastDir).toBe('in');
    expect(c.lastStatus).toBe('in');
  });

  test('presence and pinning are honestly false — a bot sees neither', () => {
    const c = conversationFrom(entry);
    expect(c.online).toBe(false);
    expect(c.typing).toBe(false);
    expect(c.pinned).toBe(false);
  });

  test('a group is flagged and tagged; a channel is tagged as one', () => {
    expect(conversationFrom({ ...entry, chat: GROUP })).toMatchObject({ group: true, tag: 'קבוצה' });
    expect(conversationFrom({ ...entry, chat: { id: -5, type: 'channel', title: 'הודעות' } }).tag).toBe('ערוץ');
  });

  test('a conversation with no messages yet has empty last fields and age 0, not NaN', () => {
    const c = conversationFrom({ chat: PRIVATE, unread: 0, readAt: 0, messages: [] });
    expect(c).toMatchObject({ lastDir: '', lastStatus: '', last: '', mins: 0 });
  });

  test('GROUP inbound carries sender + scolor; a 1:1 and our own messages carry neither', () => {
    const inbound = entry.messages[0];
    expect(messageFrom(inbound, { group: true })).toMatchObject({ sender: 'משה כהן' });
    expect(messageFrom(inbound, { group: true }).scolor).toEqual(expect.any(String));
    expect(messageFrom(inbound, { group: false }).sender).toBeUndefined();
    expect(messageFrom(entry.messages[1], { group: true }).sender).toBeUndefined();
  });

  test('an outbound message reports "sent" and stops there — a bot gets no read receipts', () => {
    expect(messageFrom(entry.messages[1], {}).status).toBe('sent');
    expect(messageFrom(entry.messages[0], {}).status).toBe('in');
  });
});

describe('sortConversations', () => {
  test('pinned first, then most recent — one rule, so a merged list stays consistent', () => {
    const list = [{ id: 'a', pinned: false, mins: 40 }, { id: 'b', pinned: false, mins: 4 }, { id: 'c', pinned: true, mins: 90 }];
    expect(sortConversations(list).map((c) => c.id)).toEqual(['c', 'b', 'a']);
  });
});

// ── a fake Bot API ──────────────────────────────────────────────────────────────────────────────

/** Records every call, so a test can assert what was sent as well as what came back. */
function api(handlers = {}) {
  const calls = [];
  const fetch = async (url, opts) => {
    const method = String(url).split('/').pop();
    const body = opts && opts.body ? JSON.parse(opts.body) : {};
    calls.push({ method, body });
    const h = handlers[method];
    if (typeof h === 'function') return h(body);
    return { ok: true, status: 200, json: async () => ({ ok: true, result: h === undefined ? [] : h }) };
  };
  fetch.calls = calls;
  return fetch;
}
const json = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });
const apiError = (code, description) => () => json({ ok: false, error_code: code, description }, code);

const UPDATES = [
  upd(1, PRIVATE, FROM, 'שלום, אפשר הצעת מחיר?', 60),
  upd(2, PRIVATE, FROM, 'תודה!', 12),
  upd(3, GROUP, { id: 777, is_bot: false, first_name: 'רחל', last_name: 'לוי' }, 'מצרפת את הקבצים', 4),
];

// ── the op surface ──────────────────────────────────────────────────────────────────────────────

const CANONICAL = ['listConversations', 'getConversation', 'sendMessage', 'markRead', 'probe'];
const opsFor = (b) => [...CANONICAL, 'reconnect', 'listGroups', 'createGroup', 'uploadMedia']
  .filter((k) => typeof b[k] === 'function');

describe('op surface', () => {
  const b = () => new TelegramBackend(TOKEN, { fetch: api() });

  test('answers every canonical op', () => {
    for (const op of CANONICAL) expect(typeof b()[op]).toBe('function');
  });

  test('DOES define reconnect — a token re-check is the op local chat cannot have', () => {
    expect(opsFor(b())).toContain('reconnect');
  });

  test('does NOT define createGroup or uploadMedia — absence is how it says "unsupported"', () => {
    // a bot CANNOT create a group (that needs a user account), and there is no standalone upload
    // endpoint: a file gets its reusable file_id only by being sent
    expect(b().createGroup).toBeUndefined();
    expect(b().uploadMedia).toBeUndefined();
    expect(opsFor(b())).toEqual(['listConversations', 'getConversation', 'sendMessage', 'markRead', 'probe', 'reconnect', 'listGroups']);
  });
});

// ── the update store ────────────────────────────────────────────────────────────────────────────

describe('listConversations', () => {
  test('is built from updates, mapped and ordered as the client expects', async () => {
    const b = new TelegramBackend(TOKEN, { fetch: api({ getUpdates: () => json({ ok: true, result: UPDATES }) }) });
    const list = await b.listConversations();
    expect(list.map((c) => c.id)).toEqual(['-1001234', '4242']);   // most recent first
    expect(list[0]).toMatchObject({ name: 'צוות הלשכה', group: true, tag: 'קבוצה', last: 'מצרפת את הקבצים', mins: 4 });
    expect(list[1]).toMatchObject({ name: 'משה כהן', handle: '@moshe', last: 'תודה!', lastDir: 'in', unread: 2 });
  });

  test('getUpdates is called WITHOUT an offset — confirming updates would delete them', async () => {
    // this is the transport's version of "do not open a second socket": a list refresh that
    // consumed the queue would make the bot's own poller miss real customer messages
    const fetch = api({ getUpdates: () => json({ ok: true, result: UPDATES }) });
    await new TelegramBackend(TOKEN, { fetch }).listConversations();
    const call = fetch.calls.find((c) => c.method === 'getUpdates');
    expect(call.body).not.toHaveProperty('offset');
    expect(call.body.timeout).toBe(0);       // a short poll: a page load must not hang for 30s
  });

  test('a 409 (something else is polling) keeps the store instead of erroring', async () => {
    // this is the NORMAL production state once inbound is wired, not an outage
    const b = new TelegramBackend(TOKEN, { fetch: api({ getUpdates: apiError(409, 'Conflict: terminated by other getUpdates request') }) });
    b.ingest(UPDATES[0]);
    const list = await b.listConversations();
    expect(list.map((c) => c.id)).toEqual(['4242']);
    expect(list.reachable).toBeUndefined();  // NOT a degraded list — the data is real
    expect(b.pollConflict).toBe(true);
  });

  test('an edit replaces its bubble instead of appending a second copy', async () => {
    const b = new TelegramBackend(TOKEN, { fetch: api() });
    b.ingest(upd(1, PRIVATE, FROM, 'טסט', 10));
    b.ingest({ update_id: 99, edited_message: { message_id: 1, chat: PRIVATE, from: FROM, text: 'טסט מתוקן', date: unix(9) } });
    const c = await b.getConversation('4242');
    expect(c.messages.map((m) => m.text)).toEqual(['טסט מתוקן']);
  });

  test('an update that carries no chat is ignored rather than stored as a blank row', async () => {
    const b = new TelegramBackend(TOKEN, { fetch: api() });
    expect(b.ingest({ update_id: 1, callback_query: { id: 'x' } })).toBeNull();
    expect(await b.listConversations()).toHaveLength(0);
  });
});

describe('getConversation', () => {
  const b = () => new TelegramBackend(TOKEN, { fetch: api({ getUpdates: () => json({ ok: true, result: UPDATES }) }) });

  test('returns the thread oldest-first with the group sender attributed', async () => {
    const c = await b().getConversation('-1001234');
    expect(c.contact.group).toBe(true);
    expect(c.messages).toHaveLength(1);
    expect(c.messages[0]).toMatchObject({ dir: 'in', text: 'מצרפת את הקבצים', sender: 'רחל לוי' });
  });

  test('a chat nothing has arrived from is null, distinctly from an outage', async () => {
    // "unknown" on this transport means "nothing has arrived from it" — the only thing a bot can
    // honestly assert, since it cannot enumerate dialogs at all
    expect(await b().getConversation('999')).toBeNull();
  });
});

// ── sending ─────────────────────────────────────────────────────────────────────────────────────

describe('sendMessage', () => {
  const sent = (body) => json({
    ok: true,
    result: { message_id: 500, chat: PRIVATE, date: Math.floor(Date.now() / 1000), text: body.text },
  });

  test('posts to sendMessage and records our own bubble — nothing else will', async () => {
    // getUpdates does not return the bot's OUTGOING messages, so without this the thread would show
    // only one side of the conversation
    const fetch = api({ getUpdates: () => json({ ok: true, result: [] }), sendMessage: sent });
    const b = new TelegramBackend(TOKEN, { fetch });
    const r = await b.sendMessage('4242', { text: 'בטח!' });
    expect(fetch.calls.find((c) => c.method === 'sendMessage').body).toEqual({ chat_id: '4242', text: 'בטח!' });
    expect(r.ok).toBe(true);
    expect(r.message).toMatchObject({ dir: 'out', text: 'בטח!', status: 'sent', mins: 0 });
    expect((await b.getConversation('4242')).messages.map((m) => m.dir)).toEqual(['out']);
  });

  test('an API refusal NEVER reports success, and keeps the description the operator needs', async () => {
    const b = new TelegramBackend(TOKEN, { fetch: api({ sendMessage: apiError(403, 'Forbidden: bot was blocked by the user') }) });
    const r = await b.sendMessage('4242', { text: 'שלום' });
    expect(r).toMatchObject({ ok: false, message: null });
    expect(r.reachable).toBe(true);          // the API answered — this is not a network problem
    expect(r.error).toMatch(/blocked by the user/);
  });

  test('an unreachable API degrades with reachable:false', async () => {
    const fetch = async () => { throw new Error('getaddrinfo ENOTFOUND api.telegram.org'); };
    const r = await new TelegramBackend(TOKEN, { fetch }).sendMessage('4242', { text: 'שלום' });
    expect(r).toMatchObject({ ok: false, reachable: false, message: null });
    expect(r.error).toMatch(/ENOTFOUND/);
  });

  test('an attachment is REFUSED, not silently dropped', async () => {
    // answering ok:true for a message whose file never went means the operator sees their own
    // bubble with the file in it and believes the customer has it
    const fetch = api({ sendMessage: sent });
    const r = await new TelegramBackend(TOKEN, { fetch }).sendMessage('4242', { text: 'הנה', attachment: { path: '/x.pdf' } });
    expect(r).toMatchObject({ ok: false, unsupported: true, message: null });
    expect(fetch.calls.find((c) => c.method === 'sendMessage')).toBeUndefined();
  });

  test('an empty message never reaches the API', async () => {
    const fetch = api({ sendMessage: sent });
    expect(await new TelegramBackend(TOKEN, { fetch }).sendMessage('4242', { text: '  ' }))
      .toMatchObject({ ok: false, message: null });
    expect(fetch.calls).toHaveLength(0);
  });
});

describe('markRead', () => {
  test('clears the badge and says plainly that it is LOCAL', async () => {
    // there is no Bot API method for this; readHistory is MTProto and a bot cannot call it, so
    // reporting remote:true would claim the other person's app now shows a read mark
    const b = new TelegramBackend(TOKEN, { fetch: api({ getUpdates: () => json({ ok: true, result: UPDATES }) }) });
    await b.listConversations();
    expect((await b.listConversations()).find((c) => c.id === '4242').unread).toBe(2);
    expect(await b.markRead('4242')).toEqual({ ok: true, unread: 0, remote: false });
    expect((await b.listConversations()).find((c) => c.id === '4242').unread).toBe(0);
  });

  test('an unknown conversation is not-found, not a cheerful ok', async () => {
    expect(await new TelegramBackend(TOKEN, { fetch: api() }).markRead('999'))
      .toMatchObject({ ok: false, notFound: true });
  });
});

// ── health ──────────────────────────────────────────────────────────────────────────────────────

describe('probe', () => {
  const me = { id: 99, is_bot: true, username: 'BinaOfficeBot', first_name: 'Bina' };

  test('a valid token is ok and names the bot', async () => {
    const b = new TelegramBackend(TOKEN, { fetch: api({ getMe: () => json({ ok: true, result: me }), getUpdates: () => json({ ok: true, result: UPDATES }) }) });
    const p = await b.probe();
    expect(p).toMatchObject({ ok: true, reachable: true, protocol: 'chat_tg_bot', conversations: 2 });
    expect(p.self).toMatchObject({ id: 99, username: '@BinaOfficeBot' });
  });

  test('a revoked token is NOT ready — and reachable:true, because the API answered', async () => {
    // the operator fix differs: one is "renew the token in BotFather", the other is "check egress"
    const p = await new TelegramBackend(TOKEN, { fetch: api({ getMe: apiError(401, 'Unauthorized') }) }).probe();
    expect(p).toMatchObject({ ok: false, reachable: true, code: 401 });
    expect(p.error).toMatch(/Unauthorized/);
  });

  test('no network is reachable:false', async () => {
    const p = await new TelegramBackend(TOKEN, { fetch: async () => { throw new Error('ETIMEDOUT'); } }).probe();
    expect(p).toMatchObject({ ok: false, reachable: false });
  });

  test('another consumer of the update queue does NOT fail the probe', async () => {
    // a bot whose updates are being consumed elsewhere is a bot that is actually working; failing
    // /readyz for it would take a healthy connection out of service
    const b = new TelegramBackend(TOKEN, { fetch: api({ getMe: () => json({ ok: true, result: me }), getUpdates: apiError(409, 'Conflict') }) });
    const p = await b.probe();
    expect(p.ok).toBe(true);
    expect(p.pollConflict).toBe(true);
  });

  test('no token at all degrades — it never throws', async () => {
    // adapters/index.js refuses to build without one; a backend that threw in its CONSTRUCTOR would
    // take down the ops of every other connection with it
    const b = new TelegramBackend(null, { fetch: api() });
    expect(await b.probe()).toMatchObject({ ok: false, reachable: false });
    expect(await b.listConversations()).toHaveLength(0);
    expect(await b.sendMessage('4242', { text: 'x' })).toMatchObject({ ok: false, message: null });
  });
});

describe('reconnect', () => {
  const me = { id: 99, is_bot: true, username: 'BinaOfficeBot', first_name: 'Bina' };

  test('re-checks the token and reports it good', async () => {
    const r = await new TelegramBackend(TOKEN, { fetch: api({ getMe: () => json({ ok: true, result: me }) }) }).reconnect();
    expect(r).toMatchObject({ ok: true, connected: true, protocol: 'chat_tg_bot' });
  });

  test('a bad token comes back as a failure with its code', async () => {
    const r = await new TelegramBackend(TOKEN, { fetch: api({ getMe: apiError(401, 'Unauthorized') }) }).reconnect();
    expect(r).toMatchObject({ ok: false, connected: false, code: 401 });
  });

  test('does NOT touch the webhook — that is standing configuration someone else owns', async () => {
    // a button labelled "reconnect" that silently detached a production webhook would stop the bot
    // receiving messages while reporting success
    const fetch = api({ getMe: () => json({ ok: true, result: me }) });
    await new TelegramBackend(TOKEN, { fetch }).reconnect();
    expect(fetch.calls.map((c) => c.method)).not.toContain('setWebhook');
    expect(fetch.calls.map((c) => c.method)).not.toContain('deleteWebhook');
  });
});

// ── degradation ─────────────────────────────────────────────────────────────────────────────────

describe('when the API is unreachable', () => {
  const down = () => new TelegramBackend(TOKEN, { fetch: async () => { throw new Error('ECONNREFUSED'); } });

  test('listConversations returns an empty list, not a throw', async () => {
    const list = await down().listConversations();
    expect(JSON.stringify(list)).toBe('[]');   // the wire shape is still a plain array
    expect(list.reachable).toBe(false);
    expect(list.error).toMatch(/ECONNREFUSED/);
  });

  test('getConversation returns a shaped-but-empty conversation flagged unreachable', async () => {
    const c = await down().getConversation('4242');
    expect(c.reachable).toBe(false);
    expect(c.messages).toEqual([]);
    expect(c.contact.name).toBe('');   // a blank header beats a crash on contact.name of undefined
  });

  test('listGroups degrades the same way', async () => {
    const g = await down().listGroups();
    expect(g).toHaveLength(0);
    expect(g.reachable).toBe(false);
  });

  test('a failure does not get hidden by the poll freshness window', async () => {
    // the sync stamp is taken BEFORE the call, so without resetting it on failure every op for the
    // next few seconds would answer "no conversations" and "no such conversation" — reporting an
    // outage as absence, which is exactly what the degraded shapes exist to prevent
    const b = down();
    await b.listConversations();
    const c = await b.getConversation('4242');
    expect(c.reachable).toBe(false);
    expect(c.error).toMatch(/ECONNREFUSED/);
  });

  test('a 409 DOES keep the window — a steady state must not be hammered', async () => {
    let calls = 0;
    const b = new TelegramBackend(TOKEN, {
      fetch: async () => { calls += 1; return json({ ok: false, error_code: 409, description: 'Conflict' }, 409); },
    });
    await b.listConversations();
    await b.listConversations();
    expect(calls).toBe(1);
  });
});

describe('listGroups', () => {
  test('is groups and channels only', async () => {
    const b = new TelegramBackend(TOKEN, { fetch: api({ getUpdates: () => json({ ok: true, result: UPDATES }) }) });
    expect((await b.listGroups()).map((c) => c.id)).toEqual(['-1001234']);
  });
});

describe('error classification', () => {
  test('a Bot API refusal is REACHABLE; only a transport failure is not', () => {
    const e = new TelegramApiError('sendMessage', 400, 'chat not found');
    expect(e.reachable).toBe(true);
    expect(e.code).toBe(400);
    expect(String(e)).toMatch(/chat not found/);
  });
  test('a non-JSON response is reported as an API error, not as a crash', async () => {
    const b = new TelegramBackend(TOKEN, { fetch: async () => ({ ok: false, status: 502, json: async () => { throw new Error('Unexpected token <'); } }) });
    expect(await b.probe()).toMatchObject({ ok: false, code: 502 });
  });
});

describe('degradedList', () => {
  test('is an ordinary empty array on the wire and to iteration', () => {
    const l = degradedList(new Error('boom'));
    expect([...l]).toEqual([]);
    expect(Object.keys(l)).toEqual([]);
    expect(l.reachable).toBe(false);
  });
});

describe('isGroupChat', () => {
  test('everything that is not a private chat is a group for rendering purposes', () => {
    expect(isGroupChat(PRIVATE)).toBe(false);
    expect(isGroupChat(GROUP)).toBe(true);
    expect(isGroupChat({ type: 'group' })).toBe(true);
    expect(isGroupChat({ type: 'channel' })).toBe(true);
  });
});
