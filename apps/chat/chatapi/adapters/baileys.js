/**
 * chat_wa_baileys — WhatsApp, through the pairing this app ALREADY has.
 *
 * THIS BACKEND OWNS NO SOCKET, AND THAT IS THE WHOLE DESIGN.
 *
 * `src/whatsapp/baileyes_app.js` runs one Baileys socket for a phone number that answers a real
 * business, and it owns that socket's entire lifecycle: pairing, the 428/515 browser-identifier
 * dance, exponential reconnect, credential writes into `data/auth_info`. A second socket built from
 * the same auth state is not a second reader — WhatsApp permits one session per registered device,
 * both processes write `creds.update` over each other, and the usual outcome is a logged-out device
 * that needs a human with the phone to re-pair. So this class READS the process-wide socket out of
 * `src/globals.appProperties` and never constructs, closes or reconfigures one.
 *
 * That has a consequence worth stating, because it is what makes the arrangement safe under
 * adapters/index.js: backends are cached by CREDENTIAL FINGERPRINT and rebuilt when it changes, and
 * `forget()` calls `close()` on the one being replaced. Since this object holds nothing but a
 * reference, rebuilding it costs nothing and — critically — `close()` here is an explicit no-op
 * (see the bottom of the file). A close() that ended the socket would let a connection being
 * *deselected in the UI* hang up the live bot.
 *
 * WHAT IS WRAPPED vs WHAT IS WRITTEN HERE:
 *   · history      WRAPPED — `src/data/wa_archive.js` (listChats / searchMessages / archiveStats).
 *                  Every WhatsApp message this bot has ever seen is already there; a second store
 *                  would be a second truth that drifts.
 *   · sending      WRAPPED — `src/whatsapp/send.js` (sendTextMessage / sendImageMessage /
 *                  sendDocumentMessage). One place knows how to talk to the socket and one place
 *                  fails when it is down.
 *   · pairing      NOT TOUCHED — reconnect() reports the QR state, it does not re-pair. See below.
 *   · projection   WRITTEN HERE — the archive's rows are shaped for an admin panel; the chat client
 *                  wants conversations and threads. That mapping is the only new logic in this file.
 *
 * THE SHAPES ARE THE CONTRACT (same fixed names local.js documents — the client renders a field it
 * cannot find as EMPTY, so a dropped `lastStatus` is a delivery tick that silently never appears):
 *
 *   conversation { id, name, handle, initials, color, tag, group, unread, pinned, online, typing,
 *                  lastDir, lastStatus, last, mins }
 *   message      { id, dir, text, mins, status, sender?, scolor? }   sender/scolor: GROUP INBOUND ONLY
 *
 * `mins` is MINUTES AGO as an integer, and `minsAgo` is IMPORTED rather than re-derived. The archive
 * writes `message_ts`/`last_message_at` as ISO-with-Z but `updated_at` as SQLite's CURRENT_TIMESTAMP
 * — zone-less `YYYY-MM-DD HH:MM:SS`, which Date.parse reads as LOCAL time. That cost this repo a bug
 * once already (every conversation three hours stale on a UTC+3 host, and still sorted plausibly, so
 * nothing looked broken); src/api/chat_adapter.js holds the corrected version and this uses it.
 *
 * DEGRADATION, exactly as local.js: an unreadable archive yields an empty list or an empty thread, a
 * write that could not happen returns { ok:false, reachable:false } and NEVER ok:true, and probe() is
 * the one place that says why. A disconnected socket is not an outage of the history — the archive
 * still reads, so the chat page still renders past conversations while the bot is waiting for a QR.
 */
const { minsAgo, initialsOf, colorOf } = require('../../src/api/chat_adapter');

const PROTOCOL = 'chat_wa_baileys';

/** How many rows to look back through for the newest NON-deleted message of a chat. A deletion is
 *  recorded by stamping `deleted_at`, not by removing the row, so the newest row is not necessarily
 *  the newest message; a handful of rows is enough for every realistic case and stays one index seek. */
const DELETED_LOOKBACK = 5;

// ── pure projection ─────────────────────────────────────────────────────────────────────────────

const isGroupJid = (jid) => String(jid || '').endsWith('@g.us');
/** Status updates and broadcast lists are not conversations — WhatsApp's own client does not list
 *  them as chats, and `src/whatsapp/chat_bot.js` already refuses to route them to a bot. */
const isBroadcastJid = (jid) => String(jid || '').endsWith('@broadcast');

/** `050-000-0006` from a JID. The archive stores the JID; the client shows a phone number. */
function jidPhone(jid) {
  const d = String(jid || '').split('@')[0].replace(/\D/g, '');
  return d ? `+${d}` : '';
}

/**
 * The preview line for a message row.
 *
 * Media is the reason this is not just `row.text`: an image has no text at all and a document's name
 * lives in a different column, so the old projection rendered a photo as an empty list row. A media
 * message with neither caption nor filename still says WHAT it was rather than nothing.
 */
function previewOf(row) {
  const t = String((row && (row.text || row.caption)) || '').trim();
  if (t) return t;
  if (row && row.media_file_name) return `📎 ${row.media_file_name}`;
  if (row && row.media_type) return `📎 ${row.media_type}`;
  return '';
}

/**
 * A `wa_chats` row (+ its newest message) → the conversation the client renders.
 *
 * `online` and `typing` are honestly FALSE. WhatsApp does report both, but only over a live
 * presence subscription on the socket (`presence.update`, which requires `presenceSubscribe` per
 * JID) — the archive records none of it. The fields still EXIST because the client reads them
 * either way, and an absent field renders as an empty badge rather than as "not typing".
 */
function conversationFrom(chat, { last = null, memberCount = 0 } = {}) {
  const jid = chat.jid;
  const group = isGroupJid(jid) || String(chat.type || '').includes('group');
  const displayName = chat.name || chat.push_name || '';
  const outbound = Boolean(last && Number(last.from_me));
  return {
    id: jid,
    name: displayName || jidPhone(jid) || jid,
    handle: group
      ? (memberCount ? `קבוצה · ${memberCount} משתתפים` : 'קבוצה')
      : jidPhone(jid),
    initials: initialsOf(displayName, jid),
    color: colorOf(jid),
    tag: group ? 'קבוצה' : '',
    group,
    unread: Number(chat.unread_count || 0),
    pinned: Boolean(Number(chat.pinned || 0)),
    online: false,
    typing: false,
    lastDir: last ? (outbound ? 'out' : 'in') : '',
    // An outbound WhatsApp message COULD carry a delivery state, but the archive stores what was
    // stored — receipts land in `wa_message_updates` as raw payloads and are not resolved per
    // message. Claiming 'read' would be inventing information; 'sent' is what we can stand behind.
    lastStatus: last ? (outbound ? 'sent' : 'in') : '',
    last: last ? previewOf(last) : '',
    // The age of the message being PREVIEWED, falling back to the chat row only when there is none.
    // The chat's own `last_message_at` is not equivalent: `upsertMessage` bumps it for every message
    // including one that is later deleted, so a row would show a two-day-old document over a
    // three-minute timestamp — the preview line and its age disagreeing about which message it is.
    mins: minsAgo((last && last.message_ts) || chat.last_message_at || chat.updated_at) ?? 0,
  };
}

/** One `wa_messages` row → a rendered message. */
function messageFrom(row, { group = false, names = null } = {}) {
  const out = Boolean(Number(row.from_me));
  const msg = {
    id: row.message_id,
    dir: out ? 'out' : 'in',
    text: previewOf(row),
    mins: minsAgo(row.message_ts) ?? 0,
    status: out ? 'sent' : 'in',
  };
  // sender + scolor are GROUP INBOUND ONLY. In a 1:1 the header already names the one other person,
  // so attributing every bubble to them is noise; on our own messages it is simply wrong.
  if (group && !out && row.participant_jid) {
    const known = names && names.get(row.participant_jid);
    msg.sender = known || jidPhone(row.participant_jid) || row.participant_jid;
    msg.scolor = colorOf(row.participant_jid);
  }
  if (row.media_file_name || row.media_type) {
    msg.attachment = {
      name: row.media_file_name || null,
      mime: row.media_mime || null,
      kind: row.media_type || null,
    };
  }
  return msg;
}

/**
 * Pinned first, then most recent — the sim's order (`(b.pinned - a.pinned) || (a.mins - b.mins)`),
 * which the adapter this replaces never applied at all, so "pinned" was decoration.
 *
 * `mins` is AGE, so smaller is newer and the comparison is ascending. Repeated here rather than
 * imported from local.js on purpose: adapters/index.js requires each backend LAZILY so one broken
 * backend module cannot stop the service from serving the others, and importing a sibling backend
 * would hand that property back (a broken `pg` install would take WhatsApp down with it).
 */
function sortConversations(list) {
  return [...list].sort((a, b) => (Number(b.pinned) - Number(a.pinned)) || (a.mins - b.mins));
}

/**
 * An empty list that still carries WHY it is empty. The op contract is
 * `listConversations() -> [conversation]`, so the degraded answer has to be an array — but "no
 * conversations" and "the archive is unreadable" must not look identical to an in-process caller.
 * Non-enumerable, so JSON, spread and iteration all see a plain empty array.
 */
function degradedList(error) {
  const arr = [];
  Object.defineProperty(arr, 'reachable', { value: false, enumerable: false });
  Object.defineProperty(arr, 'error', { value: String((error && error.message) || error), enumerable: false });
  return arr;
}

/** A locally-minted id for a bubble we just sent. See sendMessage() for why this is not the WA id. */
function localId() {
  return `wa_local_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

// ── the backend ─────────────────────────────────────────────────────────────────────────────────

class BaileysBackend {
  /**
   * @param {object} [secret]  the vault record for this connection. It carries NO session material:
   *   the WhatsApp credential is the multi-file auth state under `data/auth_info`, written by the
   *   socket owner. Anything here is a display hint, which is also why a "rotation" of this secret
   *   can safely rebuild the backend — there is no session to lose.
   * @param {object} [deps]  test seams: { archive, globals, send }.
   */
  constructor(secret = {}, deps = {}) {
    this.secret = secret || {};
    this.deps = deps || {};
    this.label = this.secret.label || this.secret.account_hint || '';
    this.lastError = null;
    this._archiveMod = null;
    this._sendMod = null;
  }

  get protocol() { return PROTOCOL; }

  // ----- the seams ------------------------------------------------------------------------------
  //
  // Required LAZILY, never at module load: wa_archive pulls in the sqlite3 native driver and send.js
  // pulls in the config/settings stack, so a top-level require would make this module unimportable
  // wherever those are absent — including the unit tests for the pure projection above, which touch
  // neither. adapters/index.js requires this file lazily for the same reason, one level up.

  get archive() {
    if (!this._archiveMod) this._archiveMod = this.deps.archive || require('../../src/data/wa_archive');
    return this._archiveMod;
  }

  get send() {
    if (!this._sendMod) this._sendMod = this.deps.send || require('../../src/whatsapp/send');
    return this._sendMod;
  }

  /**
   * The LIVE socket and its state — borrowed, never built.
   *
   * `appProperties` is the process-wide singleton `baileyes_app.js` writes on every connection
   * event, so reading it is how this backend learns the truth without holding a handle of its own.
   */
  socket() {
    const g = this.deps.globals || require('../../src/globals');
    const p = (g && g.appProperties) || {};
    return {
      sock: p.sock || null,
      connected: Boolean(p.sock && p.is_connected),
      qr: p.qr_text || null,
      number: p.botNumber || null,
      lastDisconnect: p.lastDisconnect || null,
    };
  }

  /** Every archive-touching op goes through here, so degradation is one behaviour rather than eight. */
  async _guard(fn, fallback) {
    try {
      const out = await fn();
      this.lastError = null;
      return out;
    } catch (e) {
      this.lastError = { at: new Date().toISOString(), message: String((e && e.message) || e) };
      console.error('[chat/baileys] degraded:', this.lastError.message);
      return fallback(e);
    }
  }

  /** The refusal every WRITE op shares: no socket means the message did not go out, and a caller
   *  that is told otherwise will not retry and will not tell anyone. */
  _notConnected() {
    const { qr } = this.socket();
    return {
      ok: false,
      reachable: false,
      error: qr
        ? 'הבוט אינו מחובר — יש לסרוק את קוד ה-QR'
        : 'הבוט אינו מחובר לוואטסאפ',
    };
  }

  // ----- canonical ops --------------------------------------------------------------------------

  /**
   * The conversation list, from the archive alone — no socket needed, which is the point: the
   * history stays browsable while the bot is disconnected and waiting to be re-paired.
   *
   * One archive query per chat for the preview line. That is an N+1, and it is the deliberate
   * choice: `idx_wa_messages_chat_ts` makes each one a single index seek, and the alternative is a
   * hand-written JOIN here that duplicates the archive's schema in a second place — which is the
   * thing this file exists not to do.
   */
  async listConversations({ limit = 100 } = {}) {
    return this._guard(async () => {
      const rows = (await this.archive.listChats({ limit })) || [];
      const chats = rows.filter((r) => r && r.jid && !isBroadcastJid(r.jid));
      const counts = await this._memberCounts(chats.filter((c) => isGroupJid(c.jid)).map((c) => c.jid));
      const out = [];
      for (const chat of chats) {
        out.push(conversationFrom(chat, {
          last: await this._lastMessage(chat.jid),
          memberCount: counts.get(chat.jid) || 0,
        }));
      }
      return sortConversations(out);
    }, (e) => degradedList(e));
  }

  /**
   * One conversation with its thread.
   *
   * `null` for an unknown jid — which is NOT the degraded answer below, and the difference is what
   * lets server.js answer 404 for "no such conversation" and 200-with-empty for "the archive is
   * unreadable". A jid that has MESSAGES but no `wa_chats` row still resolves, from a synthesised
   * row: that is the state right after the bot answers a number it has never spoken to, and 404 on
   * a conversation you can see in the list is worse than a header with a phone number in it.
   */
  async getConversation(id, { limit = 200 } = {}) {
    return this._guard(async () => {
      const rows = (await this.archive.listChats({ limit: 500 })) || [];
      let chat = rows.find((c) => c.jid === id) || null;
      const msgs = ((await this.archive.searchMessages({ chatJid: id, limit })) || [])
        .filter((r) => !r.deleted_at);
      if (!chat) {
        if (!msgs.length) return null;
        chat = { jid: id, type: isGroupJid(id) ? 'group' : 'private' };
      }
      const counts = isGroupJid(id) ? await this._memberCounts([id]) : new Map();
      const contact = conversationFrom(chat, { last: msgs[0] || null, memberCount: counts.get(id) || 0 });
      const names = contact.group ? await this._contactNames(msgs.map((m) => m.participant_jid)) : null;
      return {
        id,
        contact,
        // the archive orders newest-first (`ORDER BY message_ts DESC`); a thread reads oldest-first
        messages: msgs.slice().reverse().map((r) => messageFrom(r, { group: contact.group, names })),
      };
    }, (e) => ({
      id,
      contact: { id, name: '', handle: '', initials: '??', color: 'var(--muted)', tag: '', group: false },
      messages: [],
      reachable: false,
      error: String((e && e.message) || e),
    }));
  }

  /**
   * Send, through the socket the bot is already running on.
   *
   * The returned bubble carries a LOCALLY minted id, not WhatsApp's. `send.js`'s helpers do not
   * hand back the server ack, and the alternative — calling `sock.sendMessage` here — would be a
   * second copy of the send path, which is exactly the split that lets one of them keep working
   * while the other silently stops. The real id arrives moments later anyway: Baileys emits our own
   * outbound message through `messages.upsert`, and the archive writes it with its true id.
   */
  async sendMessage(conversationId, { text = '', attachment = null } = {}) {
    return this._guard(async () => {
      const body = String(text || '');
      if (!body.trim() && !attachment) {
        return { ok: false, error: 'a message needs text or an attachment', message: null };
      }
      const { sock, connected } = this.socket();
      if (!connected) return { ...this._notConnected(), message: null };

      if (attachment) {
        const path = attachment.path || attachment.storagePath || attachment.sourcePath;
        if (!path) return { ok: false, error: 'an attachment needs a path', message: null };
        const mime = attachment.mime || attachment.mimeType || '';
        if (String(mime).startsWith('image/')) {
          await this.send.sendImageMessage(sock, conversationId, path, body);
        } else {
          await this.send.sendDocumentMessage(
            sock, conversationId, path, attachment.name || attachment.fileName || 'file', mime || null, body,
          );
        }
      } else {
        await this.send.sendTextMessage(sock, conversationId, body);
      }
      return {
        ok: true,
        message: {
          id: localId(),
          dir: 'out',
          text: body || previewOf({ media_file_name: attachment && (attachment.name || attachment.fileName) }),
          mins: 0,
          status: 'sent',
        },
      };
    }, (e) => ({
      // a write that did not happen NEVER reports success — the caller must be able to retry
      ok: false, reachable: false, error: String((e && e.message) || e), message: null,
    }));
  }

  /**
   * Mark a conversation read — a REAL read receipt, sent to a real person.
   *
   * `sock.readMessages(keys)` is the whole of it: the minimal documented call, no chat mutation, no
   * `chatModify`. Note what this deliberately does NOT do — write `unread_count: 0` back into the
   * archive. `upsertChat` replaces `raw_json` wholesale, so a synthetic "chat" built just to zero a
   * counter would overwrite the stored WhatsApp payload with a two-field stub. WhatsApp reports the
   * new unread count itself on the next `chats.update`, which is the archive's own path for it.
   */
  async markRead(conversationId) {
    return this._guard(async () => {
      const { sock, connected } = this.socket();
      if (!connected) return this._notConnected();
      const rows = (await this.archive.searchMessages({ chatJid: conversationId, limit: 50 })) || [];
      const keys = rows
        .filter((r) => !Number(r.from_me) && !r.deleted_at && r.message_id)
        .slice(0, 25)
        .map((r) => ({
          remoteJid: r.chat_jid,
          id: r.message_id,
          ...(r.participant_jid ? { participant: r.participant_jid } : {}),
        }));
      if (!keys.length) return { ok: true, marked: 0, unread: 0 };
      await sock.readMessages(keys);
      return { ok: true, marked: keys.length, unread: 0 };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  /**
   * Health, for /readyz. Never throws.
   *
   * Two independent things can be wrong and they are reported separately, because the operator
   * actions differ: the SOCKET can be unpaired (scan a QR) while the ARCHIVE reads perfectly, and
   * the archive can be unreadable (a broken volume mount) while the bot is happily answering
   * customers. `reachable` is about the transport; `archive.error` is about the history.
   */
  async probe() {
    const at = Date.now();
    const { connected, qr, number, lastDisconnect } = this.socket();
    let archive = null;
    let archiveError = null;
    try {
      archive = await this.archive.archiveStats();
    } catch (e) {
      archiveError = String((e && e.message) || e);
    }
    const ok = connected && !archiveError;
    if (!ok) {
      this.lastError = {
        at: new Date().toISOString(),
        message: archiveError || 'whatsapp socket not connected',
      };
    }
    return {
      ok,
      reachable: connected,
      protocol: PROTOCOL,
      connected,
      qr: Boolean(qr),
      self: { number: number ? jidPhone(number) : '', label: this.label },
      archive: archive || null,
      ...(archiveError ? { archiveError } : {}),
      ...(connected ? {} : {
        error: qr
          ? 'הבוט אינו מחובר — נדרשת סריקת קוד QR'
          : 'הבוט אינו מחובר לוואטסאפ',
        reason: (lastDisconnect && lastDisconnect.error && lastDisconnect.error.message) || null,
      }),
      latencyMs: Date.now() - at,
    };
  }

  // ----- protocol ops -----------------------------------------------------------------------------

  /**
   * Re-pair — the op local chat cannot have, and the reason PROTOCOL_OPS exists.
   *
   * It REPORTS the pairing state and hands back the current QR; it does not tear anything down.
   * That is not timidity, it is the correct implementation: `baileyes_app.js` already reconnects on
   * its own backoff and re-emits a QR when the credential is gone, so the only thing an explicit
   * re-pair could add here is killing a socket that is serving a live business — and a socket
   * killed mid-conversation loses nothing gracefully. "Reconnect" in this UI has always meant
   * "show me the QR again"; this answers that question honestly.
   */
  async reconnect() {
    const { connected, qr, number, lastDisconnect } = this.socket();
    return {
      ok: connected || Boolean(qr),
      protocol: PROTOCOL,
      connected,
      qr_text: connected ? null : qr,
      self: { number: number ? jidPhone(number) : '' },
      ...(connected
        ? { note: 'המכשיר כבר מקושר — אין צורך בסריקה' }
        : {
          error: qr ? null : 'עדיין לא הופק קוד QR — הבוט מנסה להתחבר',
          reason: (lastDisconnect && lastDisconnect.error && lastDisconnect.error.message) || null,
        }),
    };
  }

  /** Groups this number is in, in the same conversation shape. Read from the archive, so it answers
   *  while the socket is down too. */
  async listGroups({ limit = 200 } = {}) {
    return this._guard(async () => {
      const rows = (await this.archive.listChats({ type: 'group', limit })) || [];
      const counts = await this._memberCounts(rows.map((r) => r.jid));
      const out = [];
      for (const chat of rows) {
        out.push(conversationFrom(chat, {
          last: await this._lastMessage(chat.jid),
          memberCount: counts.get(chat.jid) || 0,
        }));
      }
      return sortConversations(out);
    }, (e) => degradedList(e));
  }

  /**
   * Create a WhatsApp group. `sock.groupCreate` is a genuine transport capability, so it is
   * advertised — but it needs the live socket, and a group that was not created must not report an
   * id nobody can open.
   */
  async createGroup({ name, members = [] } = {}) {
    return this._guard(async () => {
      const subject = String(name || '').trim();
      if (!subject) return { ok: false, error: 'a group needs a name' };
      const { sock, connected } = this.socket();
      if (!connected) return this._notConnected();
      const jids = members
        .map((m) => (typeof m === 'string' ? m : (m && (m.id || m.jid))))
        .filter(Boolean)
        .map((m) => (String(m).includes('@') ? String(m) : `${String(m).replace(/\D/g, '')}@s.whatsapp.net`));
      const res = await sock.groupCreate(subject, jids);
      return { ok: true, id: (res && res.id) || null, name: subject, members: jids.length };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  // `uploadMedia` IS DELIBERATELY ABSENT, like local.js's `reconnect`. opsFor() advertises by asking
  // the object which methods it has, so not defining one is how a backend says "unsupported".
  // WhatsApp has no staging step: bytes are uploaded as PART of sending, there is no handle to get
  // back and attach later. A stub that wrote a file somewhere and returned an id would advertise a
  // capability whose id means nothing to this transport.

  /**
   * NOT A MISTAKE, AND NOT SAFE TO "FIX".
   *
   * adapters/index.js calls close() on a backend it is replacing or forgetting — on credential
   * rotation, and on `POST /api/account/select` when the operator switches to another connection.
   * The socket is NOT this object's to end: it belongs to `baileyes_app.js` and it is answering a
   * real phone. Deselecting a connection in a browser tab must not hang up a business's WhatsApp,
   * so this method exists precisely to be empty and to say so.
   */
  async close() { /* the socket belongs to src/whatsapp/baileyes_app.js — see above */ }

  // ----- internals --------------------------------------------------------------------------------

  /** The newest non-deleted message of a chat, or null. */
  async _lastMessage(jid) {
    const rows = (await this.archive.searchMessages({ chatJid: jid, limit: DELETED_LOOKBACK })) || [];
    return rows.find((r) => !r.deleted_at) || null;
  }

  /**
   * jid -> participant count, for the group subtitle the client renders ("קבוצה · 6 משתתפים").
   *
   * This reaches for the archive's own db handle because `wa_group_participants` has no listing
   * helper — one narrow read through the module's public `getDb()`, not a second schema. It is
   * guarded on its own rather than through `_guard`: a missing participant table is a cosmetic loss
   * (the subtitle falls back to "קבוצה") and must not empty the conversation list.
   */
  async _memberCounts(jids) {
    const out = new Map();
    const list = [...new Set((jids || []).filter(Boolean))];
    if (!list.length || typeof this.archive.getDb !== 'function') return out;
    try {
      const db = await this.archive.getDb();
      if (!db) return out;
      const rows = await db.all(
        `SELECT group_jid, COUNT(*) AS n FROM wa_group_participants
          WHERE group_jid IN (${list.map(() => '?').join(',')}) GROUP BY group_jid`, ...list);
      for (const r of rows || []) out.set(r.group_jid, Number(r.n || 0));
    } catch (e) {
      console.error('[chat/baileys] member counts unavailable:', e.message);
    }
    return out;
  }

  /**
   * participant jid -> display name, for group message attribution.
   *
   * Same reasoning as above: without it a group thread attributes every bubble to a raw phone
   * number, and with a failure here it falls back to exactly that rather than to nothing.
   */
  async _contactNames(jids) {
    const out = new Map();
    const list = [...new Set((jids || []).filter(Boolean))];
    if (!list.length || typeof this.archive.getDb !== 'function') return out;
    try {
      const db = await this.archive.getDb();
      if (!db) return out;
      const rows = await db.all(
        `SELECT jid, name, notify, verified_name FROM wa_contacts
          WHERE jid IN (${list.map(() => '?').join(',')})`, ...list);
      for (const r of rows || []) {
        const n = r.name || r.notify || r.verified_name;
        if (n) out.set(r.jid, n);
      }
    } catch (e) {
      console.error('[chat/baileys] contact names unavailable:', e.message);
    }
    return out;
  }
}

module.exports = {
  BaileysBackend,
  // exported for the unit tests: these are the parts that decide what the client SEES
  conversationFrom, messageFrom, sortConversations,
  previewOf, jidPhone, isGroupJid, isBroadcastJid, degradedList,
  PROTOCOL,
};
