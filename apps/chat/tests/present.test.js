/**
 * THE SHAPES THE CLIENT RENDERS — tested without a relay and without a database.
 *
 * These assertions were `tests/local_chat_backend.test.js`. They moved here with the code: the
 * engine behind `chat_local` changed (postgres -> a buzz relay) and none of this did, because it is
 * presentation, not storage. Carrying the tests across rather than rewriting them is the point —
 * they are the proof the swap did not quietly change what the operator sees.
 *
 * The reasoning is unchanged too: the part most likely to be wrong is the field mapping, and the
 * client renders a missing field as EMPTY rather than as an error — so a dropped `lastStatus` is an
 * invisible bug that only shows up as a delivery tick that never appears.
 */
const {
  conversation, message, sortConversations,
  minsAgo, initialsOf, colorOf, previewText, isOnline,
  parseMentions, resolveMentions, safeFileName, degradedList,
} = require('../chatapi/relay/present');

const ago = (mins) => new Date(Date.now() - mins * 60000);

describe('minsAgo', () => {
  test('accepts the Date node-postgres returns for timestamptz', () => {
    expect(minsAgo(ago(26))).toBe(26);
  });

  test('reads a zone-less "YYYY-MM-DD HH:MM:SS" as UTC, not as local time', () => {
    // Date.parse treats a marker-less string as LOCAL, which on a UTC+3 host aged every
    // conversation by three hours while the list still sorted plausibly — nothing looked broken.
    const s = ago(90).toISOString().replace('T', ' ').slice(0, 19);
    expect(minsAgo(s)).toBeGreaterThanOrEqual(89);
    expect(minsAgo(s)).toBeLessThanOrEqual(91);
  });

  test('null for a missing timestamp rather than a bogus 0', () => {
    expect(minsAgo(null)).toBeNull();
    expect(minsAgo('')).toBeNull();
    expect(minsAgo('not-a-date')).toBeNull();
  });

  test('never negative when the clock is slightly ahead', () => {
    expect(minsAgo(new Date(Date.now() + 60000))).toBe(0);
  });
});

describe('initialsOf', () => {
  test('first letters of the first two words', () => {
    expect(initialsOf('משה כהן', '050-000-0006')).toBe('מכ');
  });
  test('a single word takes two characters', () => {
    expect(initialsOf('מאפייה', '')).toBe('מא');
  });
  test('falls back to the handle so a nameless user still gets an avatar', () => {
    expect(initialsOf('', '050-000-0006')).toBe('33');
    expect(initialsOf('', '@BinaOfficeBot')).toBe('Bi');
    expect(initialsOf(null, null)).toBe('??');
  });
});

describe('colorOf', () => {
  test('is stable for the same key across calls', () => {
    // the colour must survive a reload and a reorder of the list; picking by index would not
    expect(colorOf('u_rachel')).toBe(colorOf('u_rachel'));
  });
  test('spreads across the palette', () => {
    const seen = new Set(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((x) => colorOf(`u_${x}`)));
    expect(seen.size).toBeGreaterThan(1);
  });
});

describe('previewText', () => {
  test('body wins', () => expect(previewText('שלום', 'inv.pdf')).toBe('שלום'));
  test('a file-only message still shows something', () => expect(previewText('', 'inv.pdf')).toBe('📎 inv.pdf'));
  test('nothing at all is an empty string, not undefined', () => expect(previewText('', null)).toBe(''));
});

describe('isOnline', () => {
  test('a recent heartbeat is online', () => expect(isOnline(ago(0))).toBe(true));
  test('an old one is not', () => expect(isOnline(ago(60))).toBe(false));
  test('never seen is not online', () => expect(isOnline(null)).toBe(false));
});

describe('parseMentions', () => {
  test('a plain @token', () => {
    expect(parseMentions('היי @רחל אפשר לבדוק?').map((m) => m.token)).toEqual(['רחל']);
  });
  test('@{…} carries a name with a space — most Hebrew names have one', () => {
    expect(parseMentions('@{רחל לוי} תודה').map((m) => m.token)).toEqual(['רחל לוי']);
  });
  test('several mentions in one message', () => {
    expect(parseMentions('@david @{רחל לוי} בבקשה').map((m) => m.token)).toEqual(['david', 'רחל לוי']);
  });
  test('an email address is not a mention', () => {
    // a LETTER/DIGIT immediately before the @ means this is the tail of an address; treating it as
    // a mention would turn every address in a message into a broken lookup
    expect(parseMentions('שלחו לperson40@example.com')).toEqual([]);
    expect(parseMentions('person21@example.com')).toEqual([]);   // a hyphen INSIDE the local part, still email
  });

  test('the ordinary Hebrew "ו-@דוד" is a mention — a hyphen before @ is not an address', () => {
    // this was a real bug: an allow-list of separators did not include the hyphen, so the mention
    // silently did not exist and the person was never notified
    expect(parseMentions('תודה @{רחל לוי} ו-@david').map((m) => m.token)).toEqual(['רחל לוי', 'david']);
  });
  test('trailing punctuation is not part of the name', () => {
    expect(parseMentions('תודה @david, מעולה').map((m) => m.token)).toEqual(['david']);
  });
  test('reports where the token began so the client can highlight it', () => {
    const [m] = parseMentions('היי @david');
    expect('היי @david'.slice(m.index)).toBe('@david');
  });
});

describe('resolveMentions', () => {
  const members = [
    { id: 'u_rachel', display_name: 'רחל לוי', handle: '@rachel' },
    { id: 'u_david', display_name: 'דוד מזרחי', handle: '@david' },
  ];

  test('matches a display name, a handle and a raw id', () => {
    expect(resolveMentions('@{רחל לוי} @david @u_rachel', members).map((m) => m.userId))
      .toEqual(['u_rachel', 'u_david']);   // u_rachel already mentioned — deduped, not repeated
  });

  test('a token that matches nobody in THIS conversation is dropped, not guessed', () => {
    // matching against every user in the database would let a mention pull in someone who cannot
    // even see the conversation; a wrong mention is worse than none
    expect(resolveMentions('@someone_else שלום', members)).toEqual([]);
  });

  test('no @ at all means no mentions', () => {
    expect(resolveMentions('הודעה רגילה', members)).toEqual([]);
  });
});

describe('sortConversations', () => {
  test('pinned first, then most recent — the sim order the old adapter never applied', () => {
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

describe('safeFileName', () => {
  test('a traversing name cannot escape the media directory', () => {
    expect(safeFileName('../../etc/passwd')).toBe('passwd');
    expect(safeFileName('C:\\Windows\\system32\\x.dll')).not.toContain('\\');
  });
  test('a leading dot cannot make a hidden file', () => {
    expect(safeFileName('.bashrc').startsWith('.')).toBe(false);
  });
  test('an empty name still produces something writable', () => {
    expect(safeFileName('')).toBe('file');
  });
});

// ── the op surface ──────────────────────────────────────────────────────────────────────────────

describe('degradedList', () => {
  test('is an ordinary empty array on the wire and to iteration', () => {
    const l = degradedList(new Error('boom'));
    expect([...l]).toEqual([]);
    expect(Object.keys(l)).toEqual([]);
    expect(l.reachable).toBe(false);
  });
});

// ── the backend against a canned result set (no server, real SQL→shape path) ─────────────────────


describe('conversation() — the list row', () => {
  const peer = { id: 'user2', name: 'משתמש 2', handle: '@user2', color: '#1c6e9c' };

  test('a 1:1 is named by the person on the other side, not by the channel', () => {
    const c = conversation({ id: 'ch1', peer });
    expect(c.name).toBe('משתמש 2');
    expect(c.group).toBe(false);
    expect(c.tag).toBe('');
  });

  test('a group is named by its title and counts its members', () => {
    const c = conversation({ id: 'g1', group: true, title: 'הנהלה', memberCount: 4 });
    expect(c.name).toBe('הנהלה');
    expect(c.handle).toBe('קבוצה · 4 משתתפים');
    expect(c.tag).toBe('קבוצה');
  });

  test('an OUTBOUND last message carries a delivery state; an inbound one never does', () => {
    const out = conversation({ id: 'c', peer, last: { id: 'm', text: 'x', at: ago(1), outbound: true, status: 'read' } });
    expect(out.lastDir).toBe('out');
    expect(out.lastStatus).toBe('read');
    const inb = conversation({ id: 'c', peer, last: { id: 'm', text: 'x', at: ago(1), outbound: false } });
    expect(inb.lastDir).toBe('in');
    // 'in' rather than a tick: storing a status here would be storing the direction twice
    expect(inb.lastStatus).toBe('in');
  });

  test('an empty conversation has no direction and no tick — not a default one', () => {
    const c = conversation({ id: 'c', peer, updatedAt: ago(30) });
    expect(c.lastDir).toBe('');
    expect(c.lastStatus).toBe('');
    expect(c.last).toBe('');
    expect(c.mins).toBe(30);
  });

  test('an attachment-only message previews as its filename', () => {
    const c = conversation({ id: 'c', peer, last: { id: 'm', text: '', fileName: 'חשבונית.pdf', at: ago(2), outbound: false } });
    expect(c.last).toBe('📎 חשבונית.pdf');
  });

  test('a group is never "online" or "typing" — there is no single peer to be either', () => {
    const c = conversation({ id: 'g', group: true, title: 'x', online: true, typing: true });
    expect(c.online).toBe(false);
    expect(c.typing).toBe(false);
  });

  test('every contract field is present even when nothing is known', () => {
    const c = conversation({ id: 'c' });
    for (const k of ['id', 'name', 'handle', 'initials', 'color', 'tag', 'group', 'unread',
                     'pinned', 'online', 'typing', 'lastDir', 'lastStatus', 'last', 'mins']) {
      expect(c).toHaveProperty(k);
    }
  });
});

describe('message() — one bubble', () => {
  test('direction and status follow `outbound`', () => {
    expect(message({ id: 'm', outbound: true, text: 'hi', at: ago(1) }).status).toBe('sent');
    expect(message({ id: 'm', outbound: false, text: 'hi', at: ago(1) }).status).toBe('in');
  });

  test('sender + scolor are GROUP INBOUND ONLY', () => {
    const sender = { id: 'u3', name: 'דנה', color: '#c0392b' };
    expect(message({ id: 'm', group: true, outbound: false, sender, at: ago(1) }).sender).toBe('דנה');
    // in a 1:1 the header already names the other person — attributing every bubble is noise
    expect(message({ id: 'm', group: false, outbound: false, sender, at: ago(1) }).sender).toBeUndefined();
    // and on our OWN message it would simply be wrong
    expect(message({ id: 'm', group: true, outbound: true, sender, at: ago(1) }).sender).toBeUndefined();
  });

  test('an attachment carries its url so the client can fetch it back', () => {
    const m = message({ id: 'm', outbound: false, at: ago(1),
      attachment: { name: 'a.png', mime: 'image/png', size: 12, url: 'http://r/media/ab.png' } });
    expect(m.attachment).toEqual({ name: 'a.png', mime: 'image/png', size: 12, path: null,
      url: 'http://r/media/ab.png', sha256: 'ab' });
    expect(m.text).toBe('📎 a.png');
  });

  test('the content hash is derived from the url when it is not given — a chip needs an address', () => {
    const m = message({ id: 'm', at: ago(1),
      attachment: { name: 'x.pdf', url: 'http://r/media/deadbeef.pdf' } });
    expect(m.attachment.sha256).toBe('deadbeef');
  });

  test('mentions appear only when there are any', () => {
    expect(message({ id: 'm', at: ago(1), mentions: [] }).mentions).toBeUndefined();
    expect(message({ id: 'm', at: ago(1), mentions: ['user2'] }).mentions).toEqual(['user2']);
  });
});
