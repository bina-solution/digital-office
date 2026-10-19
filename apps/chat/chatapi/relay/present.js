/**
 * THE SHAPES THE CHAT CLIENT RENDERS — owned in ONE place, fed by every backend.
 *
 * These functions were `adapters/local.js`'s private projection. They are here because the engine
 * behind `chat_local` changed (postgres -> a buzz relay) and NONE of this changed with it: minutes
 * ago, avatar initials, a deterministic colour, the @-mention grammar, the preview line, the sort
 * order. They are presentation, not storage, and duplicating them per backend is how the sim's
 * `lastStatus` tick and the pinned-first order got lost in the first WhatsApp adapter.
 *
 * THE SHAPES ARE THE CONTRACT (digital-office/sim/mocks/wadmin.js is the reference implementation).
 * The client reads fixed field names and renders EMPTY for any it does not find — a missing
 * `lastStatus` is not an error, it is a delivery tick that silently never appears. So the two
 * builders below are the single definition of those shapes, and every backend goes through them:
 *
 *   conversation { id, name, handle, initials, color, tag, group, unread, pinned, online, typing,
 *                  lastDir, lastStatus, last, mins }
 *   message      { id, dir, text, mins, status, sender?, scolor? }   sender/scolor: GROUP INBOUND ONLY
 *
 * `mins` is MINUTES AGO as an integer, because the client formats "לפני X" from a number.
 */
const crypto = require('crypto');
const path = require('path');

/**
 * Minutes since a timestamp. Accepts a Date (what node-postgres returns for timestamptz), an ISO
 * string, or the marker-less `YYYY-MM-DD HH:MM:SS` form.
 *
 * The marker-less case is the trap, and it is the same one the WhatsApp adapter hit: Date.parse
 * reads a zone-less string as LOCAL time, so on a UTC+3 host every conversation came out three
 * hours older than it was — and the list still SORTED correctly, so nothing looked broken. A
 * timestamp with no zone is therefore explicitly read as UTC, which is what the writer meant.
 */
function minsAgo(ts) {
  if (ts === null || ts === undefined || ts === '') return null;
  let t;
  if (ts instanceof Date) {
    t = ts.getTime();
  } else {
    let s = String(ts).trim().replace(' ', 'T');
    if (!/[Zz]$/.test(s) && !/[+-]\d{2}:?\d{2}$/.test(s)) s += 'Z';
    t = Date.parse(s);
  }
  if (Number.isNaN(t)) return null;
  // never negative: a clock a few seconds ahead must read "now", not "in the future"
  return Math.max(0, Math.round((Date.now() - t) / 60000));
}

/**
 * Avatar initials. Falls back to the handle's last two characters, because a user with no display
 * name still needs a stable avatar rather than an empty circle.
 */
function initialsOf(name, handle) {
  const clean = String(name || '').trim();
  if (clean) {
    const parts = clean.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return parts[0][0] + parts[1][0];
    return clean.slice(0, 2);
  }
  const h = String(handle || '').trim();
  const digits = h.replace(/\D/g, '');
  if (digits) return digits.slice(-2);
  const letters = h.replace(/[^\p{L}\p{N}]/gu, '');
  return letters.slice(0, 2) || '??';
}

// Deterministic colour: the same user must keep their colour across reloads and reorders, so this
// hashes the id rather than picking at random or by list position (which shifts as chats move).
// A colour here is a NAME in the office's palette (its line steps — they turn with the theme), not
// a value: the page that shows it carries the palette (the same list as src/api/chat_adapter.js).
const PALETTE = ['sky-d', 'violet', 'lime-d', 'olive-d', 'plum-d', 'muted'].map(n => `var(--${n})`);
function colorOf(key) {
  let h = 0;
  for (const ch of String(key || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/**
 * @-tokens in a message body.
 *
 * Two forms, because one is not enough: `@name` for the common case, and `@{full name}` for the
 * names that contain a space — which in Hebrew is most of them, so a parser that stopped at
 * whitespace would mention "רחל" and leave "לוי" as plain text.
 *
 * Emails are excluded by what may precede the @: a LETTER, DIGIT, `_`, `.` or `+` means this is the
 * tail of an address (`person20@example.com`), and treating that as a mention would turn every
 * address in a message into a broken lookup.
 *
 * The rule is stated as "what may NOT come before" rather than "what may", and that distinction is
 * not pedantry — it was a bug. An allow-list of separators missed `ו-@דוד`, the ordinary Hebrew way
 * of writing "and @david": the hyphen was not in the list, so the mention silently did not exist
 * and the person was never notified. A hyphen before an @ is never part of an email local part
 * (`person21@example.com` still has a LETTER immediately before the @), so excluding by character class
 * catches the address without also catching the language.
 */
function parseMentions(text) {
  const s = String(text || '');
  const out = [];
  const re = /(?<![\p{L}\p{N}_.+])@(?:\{([^}]{1,64})\}|([\p{L}\p{N}_.\-']{1,64}))/gu;
  let m = re.exec(s);
  while (m) {
    const token = (m[1] !== undefined ? m[1] : m[2]).replace(/[.,:;!?'"\-]+$/u, '');
    if (token) out.push({ token, index: m.index });
    m = re.exec(s);
  }
  return out;
}

/**
 * @-tokens resolved against the people actually in this conversation.
 *
 * Scoping to members is the point: a mention is a notification, and matching against every user in
 * the database would let a token pull in someone who cannot see the conversation. An unmatched
 * token is dropped rather than guessed — a wrong mention is worse than none.
 */
function resolveMentions(text, members) {
  const byName = new Map();
  for (const u of members || []) {
    const add = (k) => { const key = String(k || '').trim().toLowerCase(); if (key && !byName.has(key)) byName.set(key, u.id); };
    add(u.id);
    add(u.display_name || u.name);
    add(u.handle);
    add(String(u.handle || '').replace(/^@/, ''));
  }
  const seen = new Set();
  const out = [];
  for (const { token, index } of parseMentions(text)) {
    const id = byName.get(token.toLowerCase());
    if (id && !seen.has(id)) { seen.add(id); out.push({ userId: id, offset: index }); }
  }
  return out;
}

/** The list preview line: the body, or the attachment when a message is only a file. */
function previewText(body, fileName) {
  const t = String(body || '').trim();
  if (t) return t;
  return fileName ? `📎 ${fileName}` : '';
}

const ONLINE_WINDOW_MS = Number(process.env.CHAT_ONLINE_WINDOW_MS || 120000);
function isOnline(onlineAt) {
  const mins = minsAgo(onlineAt);
  return mins !== null && mins * 60000 <= ONLINE_WINDOW_MS;
}


// ── the two shapes ──────────────────────────────────────────────────────────────────────────────

/**
 * Build the conversation row the client renders, from fields a backend has already resolved.
 *
 * Deliberately NOT given a database row or a Nostr event: the moment this function knows what a
 * storage row looks like, a second copy of it appears for the second backend, and the two drift in
 * exactly the fields nobody notices are missing. Backends resolve; this shapes.
 *
 * A 1:1 conversation has no name of its own — it is named by the person on the other side — so the
 * caller passes `peer`, and a group passes `title` + `members`.
 */
function conversation({
  id, group = false, title = null, handle = null, tag = null, color = null, pinned = false,
  peer = null, memberCount = 0, unread = 0, online = false, typing = false,
  last = null, updatedAt = null,
} = {}) {
  const peerId = (peer && peer.id) || null;
  const name = group
    ? (title || handle || id)
    : ((peer && (peer.name || peer.handle)) || peerId || title || id);
  const shownHandle = group
    ? (handle || `קבוצה · ${Number(memberCount || 0)} משתתפים`)
    : ((peer && peer.handle) || handle || '');
  const has = Boolean(last && last.id);
  const outbound = has && Boolean(last.outbound);
  return {
    id,
    name,
    handle: shownHandle,
    initials: initialsOf(name, shownHandle || peerId),
    color: color || (group ? colorOf(id) : ((peer && peer.color) || colorOf(peerId || id))),
    tag: tag || (group ? 'קבוצה' : ''),
    group: Boolean(group),
    unread: Number(unread || 0),
    pinned: Boolean(pinned),
    online: group ? false : Boolean(online),
    typing: group ? false : Boolean(typing),
    lastDir: has ? (outbound ? 'out' : 'in') : '',
    // Inbound messages render as 'in'; only an outbound message carries a delivery state. Storing
    // 'in' would be storing the direction twice under a second name.
    lastStatus: has ? (outbound ? (last.status || 'sent') : 'in') : '',
    last: has ? previewText(last.text, last.fileName) : '',
    mins: minsAgo(has ? last.at : updatedAt) ?? 0,
  };
}

/** Build one rendered message from fields a backend has already resolved. */
function message({
  id, outbound = false, text = '', at = null, status = null, group = false,
  sender = null, attachment = null, mentions = null,
} = {}) {
  const msg = {
    id,
    dir: outbound ? 'out' : 'in',
    text: previewText(text, attachment && attachment.name),
    mins: minsAgo(at) ?? 0,
    status: outbound ? (status || 'sent') : 'in',
  };
  // sender + scolor are GROUP INBOUND ONLY. In a 1:1 the header already names the one other person,
  // so attributing every bubble to them is noise; on our own messages it is simply wrong.
  if (group && !outbound && sender) {
    msg.sender = sender.name || sender.handle || sender.id || '';
    msg.scolor = sender.color || colorOf(sender.id);
  }
  if (attachment && attachment.name) {
    msg.attachment = {
      name: attachment.name,
      mime: attachment.mime || null,
      size: attachment.size === null || attachment.size === undefined ? null : Number(attachment.size),
      path: attachment.path || null,
      url: attachment.url || null,
      // The content hash is the blob's ADDRESS, and the client needs it to build a download link.
      // Without it the chip rendered with the right name and size and an href of `api/media/` —
      // a link to nothing. Derived from the url when the caller did not pass it, because that is
      // where the engine puts it (`/media/<sha>.<ext>`) and a shape that is sometimes complete is
      // worse than one that is always.
      sha256: attachment.sha256
        || (String(attachment.url || '').split('/').pop() || '').split('.')[0]
        || null,
    };
  }
  const ms = mentions || [];
  if (ms.length) msg.mentions = ms;
  return msg;
}

/**
 * Pinned first, then most recent — the sim's order, and the one the first WhatsApp adapter was
 * missing entirely (it returned the list unsorted, so "pinned" was decoration).
 *
 * `mins` is AGE, so smaller is newer and the comparison is ascending. A backend that already orders
 * this way is not made redundant by it: doing it here is what makes the ordering testable without a
 * database, and what keeps a caller merging lists from two sources correct.
 */
function sortConversations(list) {
  return [...list].sort((a, b) => (Number(b.pinned) - Number(a.pinned)) || (a.mins - b.mins));
}

function newId(prefix) {
  return `${prefix}_${Date.now().toString(36)}${crypto.randomBytes(5).toString('hex')}`;
}

/** Strip anything that could escape the media directory; keep the extension readable. */
function safeFileName(name) {
  const base = path.basename(String(name || 'file'));
  const clean = base.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').replace(/^\.+/, '_').trim();
  return clean.slice(0, 120) || 'file';
}

/**
 * An empty list that still carries WHY it is empty.
 *
 * The op contract is `listConversations() -> [conversation]`, so the degraded answer has to be an
 * array — but "no conversations" and "the database is down" must not look identical to an in-process
 * caller. The properties are non-enumerable so JSON, spread and iteration see a plain empty array,
 * while server.js can read `list.reachable` to decide what to report.
 */
function degradedList(error) {
  const arr = [];
  Object.defineProperty(arr, 'reachable', { value: false, enumerable: false });
  Object.defineProperty(arr, 'error', { value: String(error && error.message || error), enumerable: false });
  return arr;
}


module.exports = {
  conversation, message, sortConversations,
  minsAgo, initialsOf, colorOf, previewText, isOnline,
  parseMentions, resolveMentions, safeFileName, newId, degradedList,
};
