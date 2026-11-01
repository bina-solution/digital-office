/**
 * The chat adapter's projection, tested on its own.
 *
 * These functions turn archive rows into what the conversation UI renders, and every one of them is
 * pure — no socket, no database, no clock beyond Date.now(). That is deliberate: it means the part
 * most likely to be wrong (field mapping) is also the part that can be checked without standing
 * anything up, so a mapping mistake fails here rather than as an empty conversation list in a
 * browser three layers away.
 */
const {
  conversationFrom, messageFrom, minsAgo, initialsOf, colorOf,
} = require('../src/api/chat_adapter');

describe('minsAgo', () => {
  test('null for a missing timestamp rather than a bogus 0', () => {
    // 0 would render as "עכשיו" — claiming a message arrived this minute when we have no idea when.
    expect(minsAgo(null)).toBeNull();
    expect(minsAgo('')).toBeNull();
    expect(minsAgo('not-a-date')).toBeNull();
  });

  test('handles the SQLite "YYYY-MM-DD HH:MM:SS" form, not just ISO', () => {
    // the archive stores CURRENT_TIMESTAMP, which uses a space, and Date.parse rejects that on some
    // engines — the reason this converts the space to a T before parsing
    const d = new Date(Date.now() - 90 * 60000);
    const sqlite = d.toISOString().replace('T', ' ').slice(0, 19);
    expect(minsAgo(sqlite)).toBeGreaterThanOrEqual(89);
    expect(minsAgo(sqlite)).toBeLessThanOrEqual(91);
  });

  test('never negative when a timestamp is slightly in the future (clock skew)', () => {
    expect(minsAgo(new Date(Date.now() + 60000).toISOString())).toBe(0);
  });
});

describe('initialsOf', () => {
  test('first letters of the first two words', () => {
    expect(initialsOf('משה כהן', 'person32@example.com')).toBe('מכ');
  });
  test('single-word names take two characters', () => {
    expect(initialsOf('מאפייה', 'person38@example.com')).toBe('מא');
  });
  test('falls back to the phone tail so a nameless contact still gets an avatar', () => {
    expect(initialsOf('', 'person32@example.com')).toBe('33');
    expect(initialsOf(null, null)).toBe('??');
  });
});

describe('colorOf', () => {
  test('is stable for the same jid', () => {
    // colour must survive a reload and a reorder of the list; picking by index would not
    expect(colorOf('person32@example.com')).toBe(colorOf('person32@example.com'));
  });
  test('differs across jids often enough to be useful', () => {
    const seen = new Set(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((x) => colorOf(`${x}@s.whatsapp.net`)));
    expect(seen.size).toBeGreaterThan(1);
  });
});

describe('conversationFrom', () => {
  test('maps a direct chat', () => {
    const c = conversationFrom({
      jid: 'person32@example.com', type: 'individual', name: 'משה כהן',
      last_message_at: new Date(Date.now() - 26 * 60000).toISOString(), unread_count: 2, pinned: 1,
    });
    expect(c.id).toBe('person32@example.com');
    expect(c.name).toBe('משה כהן');
    expect(c.handle).toBe('050-000-0006');
    expect(c.unread).toBe(2);
    expect(c.pinned).toBe(true);
    expect(c.group).toBe(false);
    expect(c.mins).toBeGreaterThanOrEqual(25);
  });

  test('detects a group from the jid even when type does not say so', () => {
    const c = conversationFrom({ jid: '123456@g.us', type: 'unknown', name: 'ספקים' });
    expect(c.group).toBe(true);
    expect(c.tag).toBe('קבוצה');
  });

  test('falls back to the phone number when there is no name at all', () => {
    const c = conversationFrom({ jid: 'person32@example.com', type: 'individual' });
    expect(c.name).toBe('050-000-0006');
  });

  test('unread/pinned coerce from SQLite integers, not truthiness of a string', () => {
    const c = conversationFrom({ jid: 'person34@example.com', type: 'individual', unread_count: 0, pinned: 0 });
    expect(c.unread).toBe(0);
    expect(c.pinned).toBe(false);
  });
});

describe('messageFrom', () => {
  test('direction comes from from_me', () => {
    expect(messageFrom({ message_id: '1', from_me: 1, text: 'hi' }).dir).toBe('out');
    expect(messageFrom({ message_id: '2', from_me: 0, text: 'hi' }).dir).toBe('in');
  });

  test('outgoing status is "sent", never "read"', () => {
    // the archive records what was stored, not read receipts; claiming 'read' would be invented
    expect(messageFrom({ message_id: '1', from_me: 1, text: 'hi' }).status).toBe('sent');
  });

  test('caption stands in for text on media messages', () => {
    expect(messageFrom({ message_id: '3', from_me: 0, caption: 'חשבונית' }).text).toBe('חשבונית');
  });

  test('a media message with neither text nor caption still shows something', () => {
    expect(messageFrom({ message_id: '4', from_me: 0, media_file_name: 'inv.pdf' }).text).toContain('inv.pdf');
  });

  test('group messages carry the sender so the thread can attribute them', () => {
    const m = messageFrom({ message_id: '5', from_me: 0, text: 'hi', participant_jid: 'person39@example.com' });
    expect(m.sender).toBe('+97250999');
  });

  test('own messages never carry a sender', () => {
    const m = messageFrom({ message_id: '6', from_me: 1, text: 'hi', participant_jid: 'person39@example.com' });
    expect(m.sender).toBeUndefined();
  });
});
