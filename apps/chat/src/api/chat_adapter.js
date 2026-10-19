/**
 * Chat client adapter — serves the conversation UI's contract from the data this app already keeps.
 *
 * The app stores every chat and message in the WhatsApp archive (src/data/wa_archive.js) and already
 * exposes them, but shaped for an admin panel: /api/wa-archive/chats returns raw `wa_chats` rows,
 * /api/wa-archive/messages/search returns raw `wa_messages` rows. The chat client wants
 * conversations and threads. Same data, different shape.
 *
 * So this is a projection, deliberately with NO storage of its own. Nothing here writes, nothing
 * caches, and every field is derived from a row that already exists — which means the client can
 * never show something the archive does not contain, and there is no second copy of the truth to
 * drift. Sending is delegated to the existing bot path rather than reimplemented.
 *
 * `/accounts` returns an ARRAY holding one WhatsApp entry today. That is the multi-provider hinge:
 * adding Telegram later appends an element instead of introducing a second UI.
 */
// Required lazily, inside register(), NOT at module load. The mapping functions below are pure and
// worth testing on their own, but wa_archive pulls in the sqlite3 native driver at import time — so
// a top-level require made `require('./chat_adapter')` fail anywhere the driver is not installed,
// including the unit tests for the very functions that never touch a database. Deferring the
// require keeps the projection independently importable, which is the point of separating it.
function archive() {
  // eslint-disable-next-line global-require
  return require('../data/wa_archive');
}

/**
 * Minutes since a stored timestamp — the client renders "ago" from a number, not a date.
 *
 * The timezone handling is the whole difficulty. SQLite's CURRENT_TIMESTAMP writes UTC in the form
 * `YYYY-MM-DD HH:MM:SS`, with NO timezone marker, and Date.parse treats a marker-less string in that
 * form as LOCAL time. On a UTC+3 host every conversation therefore came out three hours older than
 * it was: a message from five minutes ago rendered as "3 שע׳", and the list sorted plausibly enough
 * that nothing looked broken. So a timestamp that carries no zone is explicitly read as UTC, which
 * is what the writer meant.
 */
function minsAgo(ts) {
  if (!ts) return null;
  let s = String(ts).trim().replace(' ', 'T');
  // no trailing Z and no ±HH:MM offset ⇒ the writer meant UTC
  if (!/[Zz]$/.test(s) && !/[+-]\d{2}:?\d{2}$/.test(s)) s += 'Z';
  const t = Date.parse(s);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((Date.now() - t) / 60000));
}

/**
 * Hebrew initials from a display name. Falls back to the phone's last two digits, because a
 * contact that has never sent a pushName still needs a stable avatar rather than an empty circle.
 */
function initialsOf(name, jid) {
  const clean = String(name || '').trim();
  if (clean) {
    const parts = clean.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]);
    return clean.slice(0, 2);
  }
  const digits = String(jid || '').replace(/\D/g, '');
  return digits.slice(-2) || '??';
}

// Deterministic colour per conversation: the same contact must keep its colour across reloads, so
// this hashes the jid rather than picking at random or by list position (which shifts as chats move).
// A colour here is a NAME in the office's palette (its line steps — they turn with the theme), not
// a value: the page that shows it carries the palette. The same list, in the same order, as the
// page's own (ui/chat.ejs colorFor) and as chatapi's.
const PALETTE = ['sky-d', 'violet', 'lime-d', 'olive-d', 'plum-d', 'muted'].map(n => `var(--${n})`);
function colorOf(jid) {
  let h = 0;
  for (const ch of String(jid || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

function jidPhone(jid) {
  const d = String(jid || '').split('@')[0].replace(/\D/g, '');
  return d ? '+' + d : '';
}

function conversationFrom(row) {
  const isGroup = String(row.type || '').includes('group') || String(row.jid || '').includes('@g.us');
  const name = row.name || row.push_name || jidPhone(row.jid) || row.jid;
  return {
    id: row.jid,
    name,
    handle: jidPhone(row.jid),
    initials: initialsOf(row.name || row.push_name, row.jid),
    color: colorOf(row.jid),
    last: '',                                   // filled by the caller from the newest message
    mins: minsAgo(row.last_message_at || row.updated_at),
    unread: Number(row.unread_count || 0),
    pinned: !!Number(row.pinned || 0),
    group: isGroup,
    tag: isGroup ? 'קבוצה' : '',
  };
}

function messageFrom(row) {
  const out = !!Number(row.from_me || 0);
  return {
    id: row.message_id,
    dir: out ? 'out' : 'in',
    text: row.text || row.caption || (row.media_file_name ? `📎 ${row.media_file_name}` : ''),
    mins: minsAgo(row.message_ts),
    // The archive records what was stored, not per-message read receipts, so claiming 'read' would
    // be inventing information. 'sent' is what we can actually stand behind.
    status: out ? 'sent' : 'in',
    ...(row.participant_jid && !out ? { sender: jidPhone(row.participant_jid) } : {}),
  };
}

function register(app, isAuthenticated, appProperties, controller) {
  // ----- accounts / bots -----------------------------------------------------
  app.get('/api/accounts', isAuthenticated, (req, res) => {
    const connected = !!appProperties.is_connected;
    res.json({
      accounts: [{
        id: 'wa-bot',
        provider: 'whatsapp',
        label: 'וואטסאפ',
        identity: appProperties.botNumber ? jidPhone(appProperties.botNumber) : '',
        color: 'var(--olive)',
        builtin: true,
        status: connected ? 'ok' : 'error',
        reason: connected ? '' : 'הבוט אינו מחובר — נדרש סריקת QR מחדש',
        checked: new Date().toISOString(),
        log: [],
        activeBot: 'hacohanim',
      }],
      active: 'wa-bot',
    });
  });

  app.get('/api/bots', isAuthenticated, (req, res) => {
    res.json({ bots: [{ id: 'hacohanim', name: 'בוט הכהנים', desc: 'מענה אוטומטי ללקוחות ולספקים' }] });
  });

  app.post('/api/account/bot', isAuthenticated, (req, res) => {
    // Choosing which bot answers for a connection. There is exactly one bot today, so this records
    // the choice and confirms it rather than pretending to switch between options that do not exist
    // — the endpoint has to answer because the client asks, and answering honestly is cheap.
    const bot = (req.body && req.body.bot) || 'hacohanim';
    res.json({ ok: true, activeBot: bot });
  });

  app.post('/api/account/reconnect', isAuthenticated, (req, res) => {
    // Re-pairing is exactly "show me the QR again"; the socket lifecycle is owned by the bot module.
    res.json({ ok: true, qr_text: appProperties.qr_text || null, is_connected: !!appProperties.is_connected });
  });

  // ----- conversations -------------------------------------------------------
  app.get('/api/conversations', isAuthenticated, async (req, res) => {
    try {
      const { listChats, searchMessages } = archive();
      const rows = await listChats({ limit: req.query.limit || 100, offset: req.query.offset || 0 });
      const conversations = [];
      for (const row of rows || []) {
        const conv = conversationFrom(row);
        // one cheap read for the preview line — the list is unreadable without it
        const last = await searchMessages({ chatJid: row.jid, limit: 1 });
        if (last && last[0]) conv.last = messageFrom(last[0]).text;
        conversations.push(conv);
      }
      res.json({ account: 'wa-bot', conversations });
    } catch (error) {
      console.error('chat adapter: conversations failed:', error);
      res.status(500).json({ error: 'Failed to list conversations' });
    }
  });

  app.get('/api/conversation/:id', isAuthenticated, async (req, res) => {
    try {
      const jid = req.params.id;
      const { listChats, searchMessages } = archive();
      const [chat] = (await listChats({ limit: 500 })).filter((c) => c.jid === jid);
      if (!chat) return res.status(404).json({ error: 'conversation not found' });
      const rows = await searchMessages({ chatJid: jid, limit: 200 });
      // The archive returns newest-first (it orders by timestamp DESC); a thread reads oldest-first.
      const messages = (rows || []).map(messageFrom).reverse();
      res.json({ id: jid, contact: conversationFrom(chat), messages });
    } catch (error) {
      console.error('chat adapter: conversation failed:', error);
      res.status(500).json({ error: 'Failed to load conversation' });
    }
  });

  app.post('/api/conversation/:id/send', isAuthenticated, async (req, res, next) => {
    // Delegate to the existing send path rather than re-implementing delivery: one place that knows
    // how to talk to the socket, one place that fails when the bot is disconnected.
    req.body = { jid: req.params.id, text: (req.body && req.body.text) || '' };
    return controller.sendToJid(req, res, next);
  });
}

module.exports = { register, conversationFrom, messageFrom, minsAgo, initialsOf, colorOf };
