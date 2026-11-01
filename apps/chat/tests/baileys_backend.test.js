/**
 * The WHATSAPP backend's projection, its op surface and its degradation — tested without a socket
 * and without sqlite.
 *
 * Same reasoning as tests/local_chat_backend.test.js: the part most likely to be wrong is the field
 * mapping, and the client renders a missing field as EMPTY rather than as an error — so a dropped
 * `lastStatus` is an invisible bug that only shows up as a delivery tick that never appears.
 *
 * The backend tests inject a FAKE archive, a FAKE globals and a FAKE send module through the
 * constructor's `deps` seam. That is deliberate for two reasons: "the archive is unreadable" is the
 * behaviour hardest to reproduce on demand and the most important to get right, and — the reason
 * this backend has a seam at all — the REAL globals hold a live socket belonging to a bot that
 * answers a real business. A test that reached for it would be a test that can send a message to a
 * customer.
 */
const {
  BaileysBackend,
  conversationFrom, messageFrom, sortConversations,
  previewOf, jidPhone, isGroupJid, isBroadcastJid, degradedList,
} = require('../chatapi/adapters/baileys');

const JID = 'person32@example.com';
const GJID = '120363000000000000@g.us';

/** The archive stores ISO-with-Z for message timestamps. */
const iso = (mins) => new Date(Date.now() - mins * 60000).toISOString();
/** …and SQLite's zone-less CURRENT_TIMESTAMP for its own bookkeeping columns. */
const sqliteNow = (mins) => new Date(Date.now() - mins * 60000).toISOString().replace('T', ' ').slice(0, 19);

describe('jid handling', () => {
  test('a phone number is read out of the jid, not out of a contact record', () => {
    expect(jidPhone(JID)).toBe('050-000-0006');
    expect(jidPhone('')).toBe('');
  });
  test('groups and broadcasts are recognised by their domain', () => {
    expect(isGroupJid(GJID)).toBe(true);
    expect(isGroupJid(JID)).toBe(false);
    expect(isBroadcastJid('status@broadcast')).toBe(true);
  });
});

describe('previewOf', () => {
  test('text wins, then caption', () => {
    expect(previewOf({ text: 'שלום', caption: 'x' })).toBe('שלום');
    expect(previewOf({ text: null, caption: 'כיתוב' })).toBe('כיתוב');
  });
  test('a document with no caption previews as its file name', () => {
    expect(previewOf({ media_type: 'document', media_file_name: 'inv.pdf' })).toBe('📎 inv.pdf');
  });
  test('an image with neither still says WHAT it was — an empty row hides activity', () => {
    expect(previewOf({ media_type: 'image' })).toBe('📎 image');
  });
  test('nothing at all is an empty string, not undefined', () => {
    expect(previewOf({})).toBe('');
    expect(previewOf(null)).toBe('');
  });
});

describe('conversationFrom', () => {
  const chat = {
    jid: JID, type: 'private', name: 'משה כהן', push_name: null,
    last_message_at: iso(26), unread_count: 2, pinned: 0, updated_at: sqliteNow(26),
  };
  const last = { message_id: 'm2', from_me: 0, message_ts: iso(26), text: 'קיבלתי, תודה רבה 🙏' };

  test('every field the client reads is present — an absent one renders empty, silently', () => {
    const c = conversationFrom(chat, { last });
    for (const k of ['id', 'name', 'handle', 'initials', 'color', 'tag', 'group', 'unread',
      'pinned', 'online', 'typing', 'lastDir', 'lastStatus', 'last', 'mins']) {
      expect(c).toHaveProperty(k);
    }
  });

  test('a 1:1 is named by its contact and subtitled by the phone number', () => {
    const c = conversationFrom(chat, { last });
    expect(c).toMatchObject({
      id: JID, name: 'משה כהן', handle: '050-000-0006', initials: 'מכ',
      group: false, tag: '', unread: 2, pinned: false, mins: 26,
    });
  });

  test('an inbound last message is lastDir:in / lastStatus:in', () => {
    const c = conversationFrom(chat, { last });
    expect(c.lastDir).toBe('in');
    expect(c.lastStatus).toBe('in');          // 'in' is a direction, not a delivery state
    expect(c.last).toBe('קיבלתי, תודה רבה 🙏');
  });

  test('an outbound last message reports "sent" and no more than that', () => {
    // the archive keeps receipts as raw payloads in wa_message_updates, unresolved per message;
    // claiming 'read' would be inventing information
    const c = conversationFrom(chat, { last: { ...last, from_me: 1 } });
    expect(c.lastDir).toBe('out');
    expect(c.lastStatus).toBe('sent');
  });

  test('a chat with no messages yet has empty last fields and ages from its own row', () => {
    const c = conversationFrom({ ...chat, last_message_at: null, updated_at: sqliteNow(5) }, { last: null });
    expect(c.lastDir).toBe('');
    expect(c.lastStatus).toBe('');
    expect(c.last).toBe('');
    expect(c.mins).toBe(5);
  });

  test('a nameless contact is still named and still gets an avatar', () => {
    const c = conversationFrom({ ...chat, name: null, push_name: null }, { last });
    expect(c.name).toBe('050-000-0006');
    expect(c.initials).toBe('33');            // the last two digits — never an empty circle
  });

  test('push_name is used when WhatsApp gave us no saved name', () => {
    expect(conversationFrom({ ...chat, name: null, push_name: 'מאפיית הבוקר' }, { last }).name).toBe('מאפיית הבוקר');
  });

  test('unread/pinned come out of SQLite integers, not out of truthiness', () => {
    // sqlite stores booleans as 0/1 and unread as text-ish numbers; `!!'0'` is true, which would
    // have pinned every chat that was explicitly NOT pinned
    const c = conversationFrom({ ...chat, pinned: '0', unread_count: '0' }, { last });
    expect(c.pinned).toBe(false);
    expect(c.unread).toBe(0);
    expect(conversationFrom({ ...chat, pinned: 1 }, { last }).pinned).toBe(true);
  });

  test('presence is honestly false — the archive records none of it', () => {
    const c = conversationFrom(chat, { last });
    expect(c.online).toBe(false);
    expect(c.typing).toBe(false);
  });

  test('a group is tagged and subtitled with its participant count', () => {
    const g = conversationFrom(
      { jid: GJID, type: 'group', name: 'צוות הלשכה', last_message_at: iso(220), unread_count: 0, pinned: 0 },
      { last: { ...last, message_ts: iso(220) }, memberCount: 6 },
    );
    expect(g.group).toBe(true);
    expect(g.tag).toBe('קבוצה');
    expect(g.handle).toBe('קבוצה · 6 משתתפים');
  });

  test('a group whose membership we cannot count says so rather than saying "0 משתתפים"', () => {
    const g = conversationFrom({ jid: GJID, type: 'group', name: 'צוות' }, { last: null, memberCount: 0 });
    expect(g.handle).toBe('קבוצה');
  });

  test('the age is the PREVIEWED message\'s, not the chat row\'s', () => {
    // `upsertMessage` bumps `last_message_at` for every message including one later deleted, so
    // taking it here would show a 26-minute-old preview line over a 3-minute timestamp — the row
    // and its age disagreeing about which message it is
    const c = conversationFrom({ ...chat, last_message_at: iso(3) }, { last });
    expect(c.mins).toBe(26);
  });

  test('the zone-less SQLite timestamp is read as UTC, not as local time', () => {
    // Date.parse treats `YYYY-MM-DD HH:MM:SS` as LOCAL, which on a UTC+3 host aged every
    // conversation by three hours while the list still sorted plausibly — nothing looked broken.
    // last_message_at is absent here on purpose, so `updated_at` is the one being read.
    const c = conversationFrom({ jid: JID, updated_at: sqliteNow(90) }, { last: null });
    expect(c.mins).toBeGreaterThanOrEqual(89);
    expect(c.mins).toBeLessThanOrEqual(91);
  });
});

describe('messageFrom', () => {
  const base = { message_id: 'm1', chat_jid: JID, message_ts: iso(8), text: 'שלום', from_me: 0 };

  test('direction and status come from from_me, which sqlite stores as 0/1', () => {
    expect(messageFrom(base).dir).toBe('in');
    expect(messageFrom(base).status).toBe('in');
    expect(messageFrom({ ...base, from_me: 1 }).dir).toBe('out');
    expect(messageFrom({ ...base, from_me: 1 }).status).toBe('sent');
  });

  test('GROUP inbound carries sender + scolor so the thread can attribute the bubble', () => {
    const m = messageFrom({ ...base, chat_jid: GJID, participant_jid: 'person33@example.com' }, { group: true });
    expect(m.sender).toBe('050-000-0009');
    expect(typeof m.scolor).toBe('string');
  });

  test('a known contact name beats the phone number in a group thread', () => {
    const names = new Map([['person33@example.com', 'רחל לוי']]);
    const m = messageFrom({ ...base, participant_jid: 'person33@example.com' }, { group: true, names });
    expect(m.sender).toBe('רחל לוי');
  });

  test('a 1:1 inbound message carries NEITHER — the header already names the one other person', () => {
    const m = messageFrom({ ...base, participant_jid: 'person33@example.com' }, { group: false });
    expect(m.sender).toBeUndefined();
    expect(m.scolor).toBeUndefined();
  });

  test('our own group message carries no sender either — attributing it to us would be wrong', () => {
    const m = messageFrom({ ...base, from_me: 1, participant_jid: 'person34@example.com' }, { group: true });
    expect(m.sender).toBeUndefined();
  });

  test('a media message carries what the archive knows about the file', () => {
    const m = messageFrom({ ...base, text: null, media_type: 'document', media_file_name: 'inv.pdf', media_mime: 'application/pdf' });
    expect(m.text).toBe('📎 inv.pdf');
    expect(m.attachment).toEqual({ name: 'inv.pdf', mime: 'application/pdf', kind: 'document' });
  });
});

describe('sortConversations', () => {
  test('pinned first, then most recent — the order the previous adapter never applied', () => {
    const list = [
      { id: 'old', pinned: false, mins: 220 },
      { id: 'new', pinned: false, mins: 4 },
      { id: 'pin-old', pinned: true, mins: 95 },
      { id: 'pin-new', pinned: true, mins: 6 },
    ];
    expect(sortConversations(list).map((c) => c.id)).toEqual(['pin-new', 'pin-old', 'new', 'old']);
  });
  test('does not mutate the caller\'s array', () => {
    const list = [{ id: 'a', pinned: false, mins: 9 }, { id: 'b', pinned: true, mins: 9 }];
    sortConversations(list);
    expect(list.map((c) => c.id)).toEqual(['a', 'b']);
  });
});

// ── the op surface ──────────────────────────────────────────────────────────────────────────────

const CANONICAL = ['listConversations', 'getConversation', 'sendMessage', 'markRead', 'probe'];
const opsFor = (b) => [...CANONICAL, 'reconnect', 'listGroups', 'createGroup', 'uploadMedia']
  .filter((k) => typeof b[k] === 'function');

describe('op surface', () => {
  const b = () => new BaileysBackend({}, deps());

  test('answers every canonical op', () => {
    for (const op of CANONICAL) expect(typeof b()[op]).toBe('function');
  });

  test('DOES define reconnect — this is the op local chat cannot have', () => {
    expect(opsFor(b())).toContain('reconnect');
  });

  test('does NOT define uploadMedia — absence is how it says "unsupported"', () => {
    // WhatsApp has no staging step: bytes are uploaded as PART of sending, so there is no handle to
    // get back and attach later, and an id that means nothing to the transport is worse than none
    expect(b().uploadMedia).toBeUndefined();
    expect(opsFor(b())).not.toContain('uploadMedia');
  });

  test('close() exists and is a NO-OP — it must never end the socket', () => {
    // adapters/index.js closes a backend it is replacing or forgetting, which happens when the
    // operator merely SELECTS another connection. The socket belongs to baileyes_app.js and is
    // answering a real phone.
    const sock = { ws: {}, end: jest.fn(), logout: jest.fn() };
    const backend = new BaileysBackend({}, deps({ sock, connected: true }));
    return backend.close().then(() => {
      expect(sock.end).not.toHaveBeenCalled();
      expect(sock.logout).not.toHaveBeenCalled();
    });
  });
});

// ── seams ───────────────────────────────────────────────────────────────────────────────────────

const CHATS = [
  { jid: JID, type: 'private', name: 'משה כהן', last_message_at: iso(26), unread_count: 0, pinned: 0, updated_at: sqliteNow(26) },
  { jid: GJID, type: 'group', name: 'צוות הלשכה', last_message_at: iso(4), unread_count: 3, pinned: 1, updated_at: sqliteNow(4) },
  { jid: 'status@broadcast', type: 'broadcast', name: null, last_message_at: iso(1), unread_count: 0, pinned: 0 },
];
const MSGS = {
  [JID]: [
    { message_id: 'm2', chat_jid: JID, from_me: 0, message_ts: iso(26), text: 'קיבלתי, תודה רבה 🙏' },
    { message_id: 'm1', chat_jid: JID, from_me: 1, message_ts: iso(52), text: 'שולח הצעת מחיר' },
  ],
  [GJID]: [
    { message_id: 'g2', chat_jid: GJID, from_me: 0, message_ts: iso(4), text: 'מצרפת את הקבצים', participant_jid: 'person33@example.com' },
  ],
};

function deps({ sock = null, connected = false, qr = null, archive = null, send = null } = {}) {
  return {
    globals: { appProperties: { sock, is_connected: connected, qr_text: qr, botNumber: connected ? '050-000-0010' : null } },
    archive: archive || {
      listChats: async ({ type, limit = 100 } = {}) => CHATS.filter((c) => !type || c.type === type).slice(0, limit),
      searchMessages: async ({ chatJid, limit = 50 } = {}) => (MSGS[chatJid] || []).slice(0, limit),
      archiveStats: async () => ({ enabled: true, chats: CHATS.length, messages: 3 }),
      getDb: async () => null,       // the participant/contact enrichments are optional by design
    },
    send: send || { sendTextMessage: jest.fn(async () => {}), sendImageMessage: jest.fn(async () => {}), sendDocumentMessage: jest.fn(async () => {}) },
  };
}

describe('listConversations over a canned archive', () => {
  test('maps, orders and filters exactly as the client expects', async () => {
    const list = await new BaileysBackend({}, deps()).listConversations();
    // pinned first; the broadcast list is not a conversation and WhatsApp does not show it as one
    expect(list.map((c) => c.id)).toEqual([GJID, JID]);
    expect(list[0]).toMatchObject({ name: 'צוות הלשכה', group: true, tag: 'קבוצה', unread: 3, pinned: true, lastDir: 'in', last: 'מצרפת את הקבצים' });
    expect(list[1]).toMatchObject({ name: 'משה כהן', group: false, lastDir: 'in', lastStatus: 'in', mins: 26 });
  });

  test('the history reads while the socket is DOWN — a disconnected bot is not an outage', async () => {
    // this is the whole reason the list comes from the archive and not from the socket
    const list = await new BaileysBackend({}, deps({ connected: false })).listConversations();
    expect(list).toHaveLength(2);
  });

  test('a deleted newest message does not become the preview line', async () => {
    const archive = deps().archive;
    const list = await new BaileysBackend({}, deps({
      archive: {
        ...archive,
        searchMessages: async ({ chatJid }) => (chatJid === JID
          ? [{ message_id: 'm3', chat_jid: JID, from_me: 0, message_ts: iso(1), text: 'נמחקה', deleted_at: iso(0) }, ...MSGS[JID]]
          : MSGS[chatJid] || []),
      },
    })).listConversations();
    expect(list.find((c) => c.id === JID).last).toBe('קיבלתי, תודה רבה 🙏');
  });
});

describe('getConversation', () => {
  test('returns the thread oldest-first — the archive orders it newest-first', async () => {
    const c = await new BaileysBackend({}, deps()).getConversation(JID);
    expect(c.messages.map((m) => m.id)).toEqual(['m1', 'm2']);
    expect(c.contact.name).toBe('משה כהן');
  });

  test('an unknown id is null, distinctly from an outage', async () => {
    // server.js answers 404 for one and 200-with-empty for the other; collapsing them reports a
    // missing chat as an outage and an outage as a missing chat
    expect(await new BaileysBackend({}, deps()).getConversation('person35@example.com')).toBeNull();
  });

  test('a jid with messages but no chat row still opens — that is a number just replied to', async () => {
    const fresh = 'person36@example.com';
    const base = deps().archive;
    const b = new BaileysBackend({}, deps({
      archive: { ...base, searchMessages: async ({ chatJid }) => (chatJid === fresh ? [{ message_id: 'x', chat_jid: fresh, from_me: 1, message_ts: iso(1), text: 'שלום' }] : []) },
    }));
    const c = await b.getConversation(fresh);
    expect(c.messages).toHaveLength(1);
    // a phone-number header beats a 404 on a chat you can see in the list
    expect(c.contact.name).toBe('050-000-0011');
  });
});

// ── sending ─────────────────────────────────────────────────────────────────────────────────────

describe('sendMessage', () => {
  test('goes out through the EXISTING send path, on the existing socket', async () => {
    const sock = { id: 'live' };
    const send = { sendTextMessage: jest.fn(async () => {}), sendImageMessage: jest.fn(), sendDocumentMessage: jest.fn() };
    const r = await new BaileysBackend({}, deps({ sock, connected: true, send })).sendMessage(JID, { text: 'שלום' });
    expect(send.sendTextMessage).toHaveBeenCalledWith(sock, JID, 'שלום');
    expect(r.ok).toBe(true);
    expect(r.message).toMatchObject({ dir: 'out', text: 'שלום', mins: 0, status: 'sent' });
    expect(r.message.id).toEqual(expect.any(String));
  });

  test('a DISCONNECTED bot never reports a message it did not send', async () => {
    const send = { sendTextMessage: jest.fn() };
    const r = await new BaileysBackend({}, deps({ connected: false, qr: 'QR', send })).sendMessage(JID, { text: 'שלום' });
    expect(r).toMatchObject({ ok: false, reachable: false, message: null });
    expect(r.error).toMatch(/QR/);
    expect(send.sendTextMessage).not.toHaveBeenCalled();
  });

  test('a throwing socket degrades instead of 500ing the chat page', async () => {
    const send = { sendTextMessage: jest.fn(async () => { throw new Error('Connection Closed'); }) };
    const r = await new BaileysBackend({}, deps({ sock: {}, connected: true, send })).sendMessage(JID, { text: 'שלום' });
    expect(r).toMatchObject({ ok: false, reachable: false, message: null });
    expect(r.error).toMatch(/Connection Closed/);
  });

  test('an empty message is refused before it reaches the socket', async () => {
    const send = { sendTextMessage: jest.fn() };
    const r = await new BaileysBackend({}, deps({ sock: {}, connected: true, send })).sendMessage(JID, { text: '   ' });
    expect(r).toMatchObject({ ok: false, message: null });
    expect(send.sendTextMessage).not.toHaveBeenCalled();
  });

  test('an image and a document take the two existing media helpers, not a third path', async () => {
    const send = { sendTextMessage: jest.fn(), sendImageMessage: jest.fn(async () => {}), sendDocumentMessage: jest.fn(async () => {}) };
    const b = new BaileysBackend({}, deps({ sock: {}, connected: true, send }));
    await b.sendMessage(JID, { text: 'תמונה', attachment: { path: '/wa_media/a.png', mime: 'image/png', name: 'a.png' } });
    await b.sendMessage(JID, { text: '', attachment: { path: '/wa_media/i.pdf', mime: 'application/pdf', name: 'i.pdf' } });
    expect(send.sendImageMessage).toHaveBeenCalled();
    expect(send.sendDocumentMessage).toHaveBeenCalled();
  });
});

describe('markRead', () => {
  test('sends real read receipts for the INBOUND messages only', async () => {
    const sock = { readMessages: jest.fn(async () => {}) };
    const r = await new BaileysBackend({}, deps({ sock, connected: true })).markRead(JID);
    expect(r).toMatchObject({ ok: true, unread: 0, marked: 1 });
    expect(sock.readMessages).toHaveBeenCalledWith([{ remoteJid: JID, id: 'm2' }]);
  });

  test('a group receipt carries the participant — a key without one is not addressable', async () => {
    const sock = { readMessages: jest.fn(async () => {}) };
    await new BaileysBackend({}, deps({ sock, connected: true })).markRead(GJID);
    expect(sock.readMessages).toHaveBeenCalledWith([
      { remoteJid: GJID, id: 'g2', participant: 'person33@example.com' },
    ]);
  });

  test('a disconnected bot reports the failure instead of a cheerful ok', async () => {
    expect(await new BaileysBackend({}, deps({ connected: false })).markRead(JID))
      .toMatchObject({ ok: false, reachable: false });
  });
});

describe('reconnect', () => {
  test('hands back the QR and does NOT touch the socket', async () => {
    const sock = { end: jest.fn(), logout: jest.fn(), ws: { close: jest.fn() } };
    const r = await new BaileysBackend({}, deps({ sock, connected: false, qr: '2@abc' })).reconnect();
    expect(r).toMatchObject({ ok: true, connected: false, qr_text: '2@abc' });
    expect(sock.end).not.toHaveBeenCalled();
    expect(sock.logout).not.toHaveBeenCalled();
    expect(sock.ws.close).not.toHaveBeenCalled();
  });

  test('an already-paired device is told there is nothing to scan', async () => {
    const r = await new BaileysBackend({}, deps({ sock: {}, connected: true })).reconnect();
    expect(r).toMatchObject({ ok: true, connected: true, qr_text: null });
  });

  test('no connection and no QR yet is not a success', async () => {
    expect((await new BaileysBackend({}, deps({ connected: false })).reconnect()).ok).toBe(false);
  });
});

describe('probe', () => {
  test('a connected bot with a readable archive is ok', async () => {
    const p = await new BaileysBackend({}, deps({ sock: {}, connected: true })).probe();
    expect(p).toMatchObject({ ok: true, reachable: true, protocol: 'chat_wa_baileys', connected: true });
    expect(p.archive.chats).toBe(3);
    expect(p.self.number).toBe('050-000-0010');
  });

  test('an unpaired socket is NOT ready, and says which button to press', async () => {
    const p = await new BaileysBackend({}, deps({ connected: false, qr: '2@abc' })).probe();
    expect(p).toMatchObject({ ok: false, reachable: false, connected: false, qr: true });
    expect(p.error).toMatch(/QR/);
    expect(p.archive).not.toBeNull();      // the history is still readable, and that is worth saying
  });

  test('an unreadable archive is reported SEPARATELY from a down socket', async () => {
    // the operator actions differ: one is "scan a QR", the other is "the volume is not mounted"
    const base = deps().archive;
    const p = await new BaileysBackend({}, deps({
      sock: {}, connected: true,
      archive: { ...base, archiveStats: async () => { throw new Error('SQLITE_CANTOPEN'); } },
    })).probe();
    expect(p).toMatchObject({ ok: false, reachable: true, connected: true });
    expect(p.archiveError).toMatch(/SQLITE_CANTOPEN/);
  });

  test('never throws, even with nothing wired at all', async () => {
    const p = await new BaileysBackend({}, {
      globals: { appProperties: {} },
      archive: { archiveStats: async () => { throw new Error('no driver'); } },
    }).probe();
    expect(p.ok).toBe(false);
  });
});

// ── degradation ─────────────────────────────────────────────────────────────────────────────────

const DOWN = () => { throw new Error('SQLITE_CANTOPEN: unable to open database file'); };

describe('when the archive is unreadable', () => {
  const down = () => new BaileysBackend({}, deps({
    sock: {}, connected: true,
    archive: { listChats: DOWN, searchMessages: DOWN, archiveStats: DOWN, getDb: DOWN },
  }));

  test('listConversations returns an empty list, not a throw', async () => {
    const list = await down().listConversations();
    expect(Array.isArray(list)).toBe(true);
    expect(JSON.stringify(list)).toBe('[]');   // the wire shape is still a plain array
    expect(list.reachable).toBe(false);        // …while an in-process caller can still see why
    expect(list.error).toMatch(/SQLITE_CANTOPEN/);
  });

  test('getConversation returns a shaped-but-empty conversation flagged unreachable', async () => {
    const c = await down().getConversation(JID);
    expect(c.reachable).toBe(false);
    expect(c.messages).toEqual([]);
    expect(c.contact.name).toBe('');   // a blank header beats a crash on contact.name of undefined
  });

  test('markRead reports the failure rather than pretending', async () => {
    expect(await down().markRead(JID)).toMatchObject({ ok: false, reachable: false });
  });

  test('listGroups and createGroup degrade the same way', async () => {
    const groups = await down().listGroups();
    expect(groups).toHaveLength(0);
    expect(groups.reachable).toBe(false);
    expect(await new BaileysBackend({}, deps({ connected: false })).createGroup({ name: 'צוות' }))
      .toMatchObject({ ok: false, reachable: false });
  });

  test('a SEND still works — the archive being unreadable does not stop the socket', async () => {
    // the two are independent, and treating one outage as the other would silence a working bot
    const send = { sendTextMessage: jest.fn(async () => {}) };
    const b = new BaileysBackend({}, deps({
      sock: {}, connected: true, send,
      archive: { listChats: DOWN, searchMessages: DOWN, archiveStats: DOWN },
    }));
    expect((await b.sendMessage(JID, { text: 'שלום' })).ok).toBe(true);
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
