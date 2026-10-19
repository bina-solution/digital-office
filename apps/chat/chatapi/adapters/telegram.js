/**
 * chat_tg_bot — Telegram, through the Bot API, with a token from the vault.
 *
 * THE ONE THING THAT MAKES THIS BACKEND DIFFERENT FROM THE OTHER TWO: a Telegram bot has no
 * mailbox. There is no `getChats`, no `getHistory`, no way to ask "who has written to me" — the Bot
 * API is a push contract, and a conversation exists only because an update arrived carrying it.
 * (The methods that CAN enumerate dialogs are MTProto client methods; a bot account has no access
 * to them, so this is a property of Telegram, not a gap in this file.)
 *
 * So the conversation list is built from updates, in two ways that back each other up:
 *
 *   1. `ingest(update)` — the inbound path hands every update it processes to the store. This is
 *      the primary source and the only one that is exact.
 *   2. `getUpdates` with NO `offset` — a cold start (a restarted process, an operator opening the
 *      chat page before any traffic) still shows the last ~24h of pending updates.
 *
 * THE OFFSET IS OMITTED ON PURPOSE AND MUST STAY OMITTED. Passing an offset CONFIRMS updates, and a
 * confirmed update is deleted from Telegram's queue forever. A "read-only" list that quietly
 * consumed the queue would make the bot's own poller miss real customer messages — the exact class
 * of harm the WhatsApp backend avoids by never opening a second socket. And when something else IS
 * consuming (the bot's poller, or a webhook), Telegram answers `409 Conflict`: that is expected, not
 * an outage, so it degrades to the store and probe() says so.
 *
 * THE SHAPES ARE THE CONTRACT (the client renders a field it cannot find as EMPTY):
 *
 *   conversation { id, name, handle, initials, color, tag, group, unread, pinned, online, typing,
 *                  lastDir, lastStatus, last, mins }
 *   message      { id, dir, text, mins, status, sender?, scolor? }   sender/scolor: GROUP INBOUND ONLY
 *
 * `mins` is MINUTES AGO as an integer. Telegram timestamps are UNIX SECONDS, so they carry no zone
 * ambiguity at all — but `minsAgo` is still imported from src/api/chat_adapter.js rather than
 * re-derived, because one corrected implementation of "how old is this" is the whole point of having
 * fixed it once (the zone-less-timestamp bug it was written for is documented there).
 *
 * DEGRADATION, exactly as local.js: an unreachable API yields an empty list or an empty thread, a
 * send that did not happen returns { ok:false, reachable:false } and NEVER ok:true, and probe() is
 * the one place that says why. A missing token normally fails at build() in adapters/index.js; if
 * one is ever constructed without it, every op degrades and nothing throws.
 */
const { minsAgo, initialsOf, colorOf } = require('../../src/api/chat_adapter');

const PROTOCOL = 'chat_tg_bot';

const API_BASE = (process.env.TELEGRAM_API_BASE || 'https://api.telegram.org').replace(/\/+$/, '');
const CALL_TIMEOUT_MS = Number(process.env.CHAT_TG_TIMEOUT_MS || 8000);
/** How long a `getUpdates` warm-up is considered fresh. Short enough that a message arriving while
 *  the page is open shows up on the next poll, long enough that clicking around the UI does not
 *  spend the bot's rate limit on a list it already has. */
const SYNC_TTL_MS = Number(process.env.CHAT_TG_SYNC_TTL_MS || 3000);
/** Bounded memory: this store is a cache of a push feed, not a database. */
const MAX_CHATS = Number(process.env.CHAT_TG_MAX_CHATS || 200);
const MAX_MESSAGES = Number(process.env.CHAT_TG_MAX_MESSAGES || 300);

// ── pure projection ─────────────────────────────────────────────────────────────────────────────

/** Telegram dates are UNIX SECONDS; minsAgo() reads timestamps, so the conversion happens once here
 *  rather than at every call site. */
function minsAgoUnix(sec) {
  if (!sec) return null;
  const n = Number(sec);
  if (!Number.isFinite(n)) return null;
  return minsAgo(new Date(n * 1000).toISOString());
}

const isGroupChat = (chat) => Boolean(chat) && chat.type !== 'private';

/** The display name of a chat: a group's title, or a person's full name. */
function chatName(chat) {
  if (!chat) return '';
  if (chat.title) return chat.title;
  const full = [chat.first_name, chat.last_name].filter(Boolean).join(' ').trim();
  if (full) return full;
  if (chat.username) return `@${chat.username}`;
  return String(chat.id || '');
}

/**
 * The subtitle line. A bot knows a @username when there is one; it does NOT know a phone number
 * (Telegram does not expose one to bots) and does not know a member count without an extra API call
 * per group, so a group without a username says what it is rather than inventing a number.
 */
function chatHandle(chat) {
  if (!chat) return '';
  if (chat.username) return `@${chat.username}`;
  if (chat.type === 'channel') return 'ערוץ';
  if (isGroupChat(chat)) return 'קבוצה';
  return chat.id ? `#${chat.id}` : '';
}

/** The name to attribute a group bubble to — the SENDER, which in a group is not the chat. */
function senderName(from) {
  if (!from) return '';
  const full = [from.first_name, from.last_name].filter(Boolean).join(' ').trim();
  return full || (from.username ? `@${from.username}` : String(from.id || ''));
}

/**
 * The text of a Telegram message, including the ones that have none.
 *
 * A photo carries `caption` or nothing at all, a document carries a file name — an attachment-only
 * message that previewed as an empty row is a conversation the operator cannot see has activity.
 */
function textOf(m) {
  const t = String((m && (m.text || m.caption)) || '').trim();
  if (t) return t;
  if (m) {
    if (m.document) return `📎 ${m.document.file_name || 'קובץ'}`;
    if (m.photo) return '📎 תמונה';
    if (m.voice) return '📎 הודעה קולית';
    if (m.audio) return `📎 ${m.audio.file_name || 'שמע'}`;
    if (m.video) return '📎 וידאו';
    if (m.sticker) return m.sticker.emoji || '📎 מדבקה';
    if (m.location) return '📎 מיקום';
    if (m.contact) return '📎 איש קשר';
  }
  return '';
}

/** The message payload of an update, whichever of the five shapes it arrived in. */
function messageOf(update) {
  if (!update) return null;
  return update.message || update.edited_message || update.channel_post || update.edited_channel_post || null;
}

/**
 * A stored entry → the message the client renders.
 *
 * `status` for an outbound message is 'sent' and stops there. Telegram's `sendMessage` returns the
 * created Message, which proves it was accepted — it says nothing about delivery to the device or
 * about the recipient reading it, and a bot receives no read receipts at all. 'delivered'/'read'
 * here would be decoration on top of information we do not have.
 */
function messageFrom(entry, { group = false } = {}) {
  const msg = {
    id: String(entry.id),
    dir: entry.dir,
    text: entry.text,
    mins: minsAgoUnix(entry.date) ?? 0,
    status: entry.dir === 'out' ? 'sent' : 'in',
  };
  // sender + scolor are GROUP INBOUND ONLY — in a 1:1 the header already names the one other person.
  if (group && entry.dir === 'in' && entry.senderId) {
    msg.sender = entry.senderName || String(entry.senderId);
    msg.scolor = colorOf(String(entry.senderId));
  }
  return msg;
}

/**
 * A stored chat → the conversation the client renders.
 *
 * `online`, `typing` and `pinned` are honestly FALSE. A bot sees no presence (there is no
 * `getUserStatus` for bots), typing is an update it can SEND but never receives, and which chats a
 * human pinned in their own client is not visible to a bot at all. The fields still EXIST because
 * the client reads them either way.
 */
function conversationFrom(entry) {
  const chat = entry.chat || {};
  const group = isGroupChat(chat);
  const last = entry.messages.length ? entry.messages[entry.messages.length - 1] : null;
  const name = chatName(chat);
  const id = String(chat.id);
  return {
    id,
    name,
    handle: chatHandle(chat),
    initials: initialsOf(name, id),
    color: colorOf(id),
    tag: chat.type === 'channel' ? 'ערוץ' : (group ? 'קבוצה' : ''),
    group,
    unread: Number(entry.unread || 0),
    pinned: false,
    online: false,
    typing: false,
    lastDir: last ? last.dir : '',
    lastStatus: last ? (last.dir === 'out' ? 'sent' : 'in') : '',
    last: last ? last.text : '',
    mins: (last ? minsAgoUnix(last.date) : null) ?? 0,
  };
}

/** Pinned first, then most recent. Nothing is pinned on this transport, so in practice this sorts by
 *  recency — it is still written in full because the ORDER is the contract, not the current data,
 *  and a caller merging this list with another backend's must get one consistent rule. */
function sortConversations(list) {
  return [...list].sort((a, b) => (Number(b.pinned) - Number(a.pinned)) || (a.mins - b.mins));
}

/** An empty list that still carries WHY it is empty — non-enumerable, so JSON and iteration see a
 *  plain empty array while an in-process caller can read `.reachable`. */
function degradedList(error) {
  const arr = [];
  Object.defineProperty(arr, 'reachable', { value: false, enumerable: false });
  Object.defineProperty(arr, 'error', { value: String((error && error.message) || error), enumerable: false });
  return arr;
}

/** A Bot API error that came back as a well-formed `{ok:false, description}` — the API is REACHABLE
 *  and refused, which is a different operator problem from the network being down. */
class TelegramApiError extends Error {
  constructor(method, code, description) {
    super(`telegram ${method}: ${code || '?'} ${description || ''}`.trim());
    this.name = 'TelegramApiError';
    this.code = code || 0;
    this.description = description || '';
    this.reachable = true;
  }
}

// ── the backend ─────────────────────────────────────────────────────────────────────────────────

class TelegramBackend {
  /**
   * @param {string} token  the BotFather token. adapters/index.js refuses to build without one, so
   *   an absent token here is only reachable in tests — it degrades rather than throwing, because a
   *   backend that throws in its CONSTRUCTOR takes down the ops of every other connection with it.
   * @param {object} [deps]  test seams: { fetch, now }.
   */
  constructor(token, deps = {}) {
    this.token = token || null;
    this.deps = deps || {};
    this.fetch = this.deps.fetch || ((...a) => fetch(...a));
    this.base = `${API_BASE}/bot${this.token}`;
    /** chat id -> { chat, messages:[entry], unread, readAt } */
    this._chats = new Map();
    this._syncedAt = 0;
    this.pollConflict = false;
    this.self = null;
    this.lastError = null;
  }

  get protocol() { return PROTOCOL; }

  // ----- transport ------------------------------------------------------------------------------

  /**
   * One Bot API call.
   *
   * The two failure modes are kept distinct all the way up: `fetch` throwing means UNREACHABLE (dns,
   * timeout, no egress) and callers degrade; a `{ok:false}` body means the API answered and refused
   * (401 revoked token, 403 blocked by the user, 409 someone else is polling) and the operator needs
   * to see the description, not "network error".
   */
  async _call(method, body = {}) {
    if (!this.token) throw new TelegramApiError(method, 401, 'no bot token configured');
    let res;
    try {
      res = await this.fetch(`${this.base}/${method}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(CALL_TIMEOUT_MS),
      });
    } catch (e) {
      const err = new Error(`telegram unreachable: ${e.message}`);
      err.reachable = false;
      throw err;
    }
    let payload;
    try {
      payload = await res.json();
    } catch (e) {
      throw new TelegramApiError(method, res.status, 'response was not JSON');
    }
    if (!payload || payload.ok !== true) {
      throw new TelegramApiError(method, (payload && payload.error_code) || res.status, payload && payload.description);
    }
    return payload.result;
  }

  /** Degradation in one place, as local.js does it — so eight ops cannot each invent their own. */
  async _guard(fn, fallback) {
    try {
      const out = await fn();
      this.lastError = null;
      return out;
    } catch (e) {
      this.lastError = { at: new Date().toISOString(), message: String((e && e.message) || e) };
      console.error('[chat/telegram] degraded:', this.lastError.message);
      return fallback(e);
    }
  }

  // ----- the store ------------------------------------------------------------------------------

  /**
   * Record one update. PUBLIC on purpose: the inbound path (a poller or a webhook route) calls this
   * for every update it handles, which is what makes the conversation list exact rather than
   * dependent on whatever `getUpdates` happens to still have queued.
   */
  ingest(update) {
    const m = messageOf(update);
    if (!m || !m.chat || m.chat.id === undefined || m.chat.id === null) return null;
    const id = String(m.chat.id);
    const entry = this._chats.get(id) || { chat: m.chat, messages: [], unread: 0, readAt: 0 };
    entry.chat = m.chat;   // titles and usernames change; the newest update wins
    const own = Boolean(m.from && m.from.is_bot && this.self && m.from.id === this.self.id);
    const rec = {
      id: m.message_id,
      dir: own ? 'out' : 'in',
      text: textOf(m),
      date: m.date,
      senderId: m.from ? m.from.id : null,
      senderName: senderName(m.from),
    };
    // An EDIT arrives as a new update carrying the same message_id — it must replace the bubble, not
    // append a second copy of it.
    const at = entry.messages.findIndex((x) => x.id === rec.id);
    if (at >= 0) entry.messages[at] = rec; else entry.messages.push(rec);
    entry.messages.sort((a, b) => (a.date || 0) - (b.date || 0));
    if (entry.messages.length > MAX_MESSAGES) entry.messages = entry.messages.slice(-MAX_MESSAGES);
    entry.unread = entry.messages.filter((x) => x.dir === 'in' && (x.date || 0) > entry.readAt).length;
    this._chats.set(id, entry);
    this._evict();
    return entry;
  }

  /** Keep the newest MAX_CHATS conversations. This is a cache of a push feed, not storage. */
  _evict() {
    if (this._chats.size <= MAX_CHATS) return;
    const byAge = [...this._chats.entries()].sort((a, b) => {
      const la = a[1].messages[a[1].messages.length - 1];
      const lb = b[1].messages[b[1].messages.length - 1];
      return ((lb && lb.date) || 0) - ((la && la.date) || 0);
    });
    for (const [id] of byAge.slice(MAX_CHATS)) this._chats.delete(id);
  }

  /**
   * Warm the store from Telegram's pending queue.
   *
   * NO OFFSET — see the file header. `timeout: 0` makes it a short poll rather than a long one, so a
   * page load never hangs for 30 seconds waiting for a message that may not come.
   *
   * A 409 means something else is already consuming updates (the bot's own poller, or a webhook is
   * registered). That is the NORMAL production state once inbound is wired, not an error: the store
   * is being fed by `ingest()` instead, so the conflict is recorded for probe() and swallowed.
   */
  async _sync({ force = false } = {}) {
    if (!this.token) return false;
    const now = Date.now();
    if (!force && now - this._syncedAt < SYNC_TTL_MS) return false;
    this._syncedAt = now;
    try {
      const updates = await this._call('getUpdates', {
        timeout: 0,
        limit: 100,
        allowed_updates: ['message', 'edited_message', 'channel_post', 'edited_channel_post'],
      });
      this.pollConflict = false;
      for (const u of updates || []) this.ingest(u);
      return true;
    } catch (e) {
      if (e instanceof TelegramApiError && e.code === 409) {
        this.pollConflict = true;
        return false;   // a conflict is a steady state, so the TTL still applies — do not hammer
      }
      // Any OTHER failure must not be hidden by the freshness window. The stamp is taken before the
      // call, so leaving it would make every op for the next few seconds answer "no conversations"
      // and "no such conversation" — reporting an outage as absence, which is the one thing the
      // degraded shapes exist to prevent.
      this._syncedAt = 0;
      throw e;
    }
  }

  // ----- canonical ops --------------------------------------------------------------------------

  /** The conversation list — the store, warmed by a non-destructive poll. */
  async listConversations({ limit = 200 } = {}) {
    return this._guard(async () => {
      await this._sync();
      const list = [...this._chats.values()].map((e) => conversationFrom(e));
      return sortConversations(list).slice(0, limit);
    }, (e) => degradedList(e));
  }

  /**
   * One conversation with its thread.
   *
   * `null` for a chat id the store has never seen — distinct from the degraded answer below, so
   * server.js can answer 404 for "no such conversation" and 200-with-empty for "the API is
   * unreachable". Note what "unknown" means on this transport: not "no such chat on Telegram" but
   * "nothing has arrived from it", which is the only thing a bot can honestly assert.
   */
  async getConversation(id, { limit = 300 } = {}) {
    return this._guard(async () => {
      await this._sync();
      const entry = this._chats.get(String(id));
      if (!entry) return null;
      const contact = conversationFrom(entry);
      return {
        id: String(id),
        contact,
        messages: entry.messages.slice(-limit).map((m) => messageFrom(m, { group: contact.group })),
      };
    }, (e) => ({
      id: String(id),
      contact: { id: String(id), name: '', handle: '', initials: '??', color: 'var(--muted)', tag: '', group: false },
      messages: [],
      reachable: false,
      error: String((e && e.message) || e),
    }));
  }

  /**
   * Send.
   *
   * An ATTACHMENT IS REFUSED rather than dropped. Telegram takes files through `sendDocument` as
   * multipart or as a URL Telegram itself can fetch — neither is wired here yet, and the one
   * unacceptable behaviour is answering ok:true for a message whose file never went: the operator
   * sees their own bubble with the file in it and believes the customer has it.
   */
  async sendMessage(conversationId, { text = '', attachment = null } = {}) {
    return this._guard(async () => {
      const body = String(text || '');
      if (attachment) {
        return { ok: false, unsupported: true, error: 'שליחת קבצים בטלגרם אינה נתמכת עדיין', message: null };
      }
      if (!body.trim()) return { ok: false, error: 'a message needs text', message: null };
      const sent = await this._call('sendMessage', { chat_id: conversationId, text: body });
      // Record our own bubble: nothing else will. Telegram's getUpdates does not return the bot's
      // outgoing messages, so without this the thread would show only one side of the conversation.
      const entry = this._chats.get(String(conversationId))
        || { chat: (sent && sent.chat) || { id: conversationId, type: 'private' }, messages: [], unread: 0, readAt: 0 };
      entry.chat = (sent && sent.chat) || entry.chat;
      entry.messages.push({
        id: sent.message_id,
        dir: 'out',
        text: textOf(sent) || body,
        date: sent.date || Math.floor(Date.now() / 1000),
        senderId: null,
        senderName: '',
      });
      if (entry.messages.length > MAX_MESSAGES) entry.messages = entry.messages.slice(-MAX_MESSAGES);
      this._chats.set(String(conversationId), entry);
      return {
        ok: true,
        message: messageFrom(entry.messages[entry.messages.length - 1], { group: isGroupChat(entry.chat) }),
      };
    }, (e) => ({
      // a write that did not happen NEVER reports success — the caller must be able to retry
      ok: false,
      reachable: e && e.reachable === false ? false : true,
      error: String((e && e.message) || e),
      message: null,
    }));
  }

  /**
   * Mark a conversation read — LOCALLY, and the answer says so.
   *
   * There is no Bot API method for this. `readHistory` is MTProto and a bot cannot call it, so the
   * only honest meaning of "read" for a bot account is "the operator has seen it here", which is a
   * watermark on our own side. Reporting `remote:false` is the difference between a badge that
   * clears and a claim that the other person's app now shows two blue ticks.
   */
  async markRead(conversationId) {
    const entry = this._chats.get(String(conversationId));
    if (!entry) return { ok: false, notFound: true, error: `no conversation ${conversationId}` };
    const last = entry.messages[entry.messages.length - 1];
    entry.readAt = (last && last.date) || Math.floor(Date.now() / 1000);
    entry.unread = 0;
    return { ok: true, unread: 0, remote: false };
  }

  /**
   * Health, for /readyz. Never throws.
   *
   * `getMe` is the right probe: it is the cheapest authenticated call, it is not rate-limited in
   * practice, and it distinguishes the three states an operator can act on — unreachable (network),
   * 401 (the token was revoked in BotFather), ok. `pollConflict` is reported but does NOT fail the
   * probe: another consumer of the update queue is the normal state of a bot that is actually
   * working, and failing /readyz for it would take a healthy connection out of service.
   */
  async probe() {
    const at = Date.now();
    if (!this.token) {
      return {
        ok: false, reachable: false, protocol: PROTOCOL,
        error: 'no bot token configured', latencyMs: Date.now() - at,
      };
    }
    try {
      const me = await this._call('getMe');
      this.self = me;
      this.lastError = null;
      // a warm-up, not part of the verdict: a failed poll must not report a healthy token as down
      try { await this._sync(); } catch (e) { console.error('[chat/telegram] sync during probe:', e.message); }
      return {
        ok: true,
        reachable: true,
        protocol: PROTOCOL,
        self: { id: me.id, username: me.username ? `@${me.username}` : '', name: me.first_name || '' },
        conversations: this._chats.size,
        pollConflict: this.pollConflict,
        ...(this.pollConflict
          ? { note: 'עדכונים נצרכים על-ידי מאזין אחר — רשימת השיחות מתעדכנת מהנתונים הנכנסים' }
          : {}),
        latencyMs: Date.now() - at,
      };
    } catch (e) {
      this.lastError = { at: new Date().toISOString(), message: String((e && e.message) || e) };
      return {
        ok: false,
        // reachable distinguishes "no network" from "the API answered and refused" — different fixes
        reachable: e && e.reachable === true,
        protocol: PROTOCOL,
        ...(e instanceof TelegramApiError ? { code: e.code } : {}),
        error: this.lastError.message,
        latencyMs: Date.now() - at,
      };
    }
  }

  // ----- protocol ops -----------------------------------------------------------------------------

  /**
   * Re-check the token — Telegram's equivalent of WhatsApp's re-pair, and the op local chat cannot
   * have.
   *
   * There is no session to re-establish (every call is a fresh HTTPS request), so "reconnect" here
   * means: is this credential still good? It deliberately does NOT call `deleteWebhook` or
   * `setWebhook`. Those are standing configuration owned by whoever wired inbound delivery, and a
   * button labelled "reconnect" that silently detached a production webhook would stop the bot
   * receiving messages while reporting success.
   */
  async reconnect() {
    const p = await this.probe();
    return {
      ok: p.ok,
      protocol: PROTOCOL,
      connected: p.ok,
      ...(p.self ? { self: p.self } : {}),
      ...(p.error ? { error: p.error } : {}),
      ...(p.code ? { code: p.code } : {}),
      ...(p.ok ? { note: 'הטוקן תקף' } : {}),
    };
  }

  /** Groups and channels this bot is in, from the same store. */
  async listGroups() {
    return this._guard(async () => {
      await this._sync();
      const list = [...this._chats.values()].filter((e) => isGroupChat(e.chat)).map((e) => conversationFrom(e));
      return sortConversations(list);
    }, (e) => degradedList(e));
  }

  // `createGroup` and `uploadMedia` ARE DELIBERATELY ABSENT, the same way local.js omits `reconnect`:
  // opsFor() advertises by asking the object which methods it has, so not defining one is how a
  // backend says "unsupported".
  //   · createGroup — a bot CANNOT create a group or a channel. Telegram requires a user account for
  //     it; a bot can only be added to one that already exists.
  //   · uploadMedia — there is no standalone upload endpoint. A file gets its reusable `file_id`
  //     only by being SENT, so there is no handle to hand back and attach later.
}

module.exports = {
  TelegramBackend,
  // exported for the unit tests: these are the parts that decide what the client SEES
  conversationFrom, messageFrom, sortConversations,
  minsAgoUnix, chatName, chatHandle, senderName, textOf, messageOf, isGroupChat,
  degradedList, TelegramApiError,
  PROTOCOL,
};
