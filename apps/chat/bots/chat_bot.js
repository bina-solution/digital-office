/**
 * THE BOT RUNTIME.
 *
 * Owns exactly three things and nothing else:
 *   1. DISCOVERY   — which bots exist (one folder per bot, `index.js` is its manifest).
 *   2. ATTACHMENT  — which bot answers on which connection (one bot per connection, like the sim).
 *   3. DISPATCH    — turn a normalised inbound message into `bot.onMessage(msg, ctx)`, where `ctx` is
 *                    built from the ABSTRACT backend (chatapi/adapters) and never from a transport.
 *
 * It knows nothing about Baileys, Telegram or the local chat tables. The whole point of this file is
 * that `hacohen-bot` — a bot that does real document intake and dispatches agent jobs — was written
 * against WhatsApp and now runs unchanged on any backend that can `sendMessage(conversationId, {text})`.
 *
 * The message and ctx shapes, and WHY each field exists, are in ./README.md. Read that before adding
 * a field here: every field is a thing every future transport must now be able to produce.
 */
const fs = require('fs');
const path = require('path');

const intent = require('./intent');
const { runExclusive } = require('../src/utils/user_lock');

/**
 * The synthetic "no bot" entry. The sim lists it as a first-class choice and that is right: an
 * operator turning automation OFF for a connection is a normal thing to do, and it must be expressible
 * in the same widget as turning it on rather than by a separate "disable" toggle somewhere else.
 */
const NO_BOT = { id: 'none', name: 'ללא בוט — שיחה ידנית', desc: 'ללא מענה אוטומטי; כל ההודעות מנוהלות ידנית.' };

/**
 * Default wiring, keyed by PROTOCOL rather than by connection id.
 *
 * It has to be by protocol, because NO connection id in the system is knowable ahead of time. Every
 * instance — private profiles included, now that they are ordinary vault instances — is
 * `<protocol>-<8hex>`, and the hex is minted when the instance is created. An earlier version keyed
 * these `'local-chat'`/`'wa-baileys'`, which matched no id the connections service ever issues, so
 * NEITHER default applied.
 *
 * The WhatsApp entry is not decoration: hacohen-bot is live and answering a real phone. Without it
 * this refactor silently switches the production number off the moment it deploys — the worst kind of
 * regression, because nothing errors, messages just stop being answered.
 */
const DEFAULT_ATTACHMENTS = {
  chat_local: 'hacohen-bot',
  chat_wa_baileys: 'hacohen-bot',
};

/** Connection ids are `<protocol>-<suffix>`; the protocol is what a default can be keyed on. */
function protocolOf(connectionId) {
  const id = String(connectionId || '');
  for (const p of Object.keys(DEFAULT_ATTACHMENTS)) {
    if (id === p || id.startsWith(`${p}-`)) return p;
  }
  return null;
}

// ── discovery ─────────────────────────────────────────────────────────────────
/** connection id -> bot id. EXPLICIT choices only; defaults are resolved at read time. */
const _attached = new Map();
/** bot id -> bot module */
let _bots = null;
let _loadedFrom = null;

// ── attachment persistence ────────────────────────────────────────────────────
/**
 * Which bot answers on which connection has to survive a restart, for the same reason the ACTIVE
 * connection pointer does (connections_client.select): a container recreate is routine, and an
 * in-memory Map means every deploy silently reverts the operator's choice to `none`. Observed exactly
 * that on each redeploy before this existed.
 *
 * Same volume and the same atomic tmp+rename as the active pointer, so a half-written file can never
 * be read back as a partial set of attachments.
 */
const STATE_DIR = process.env.CHAT_STATE_DIR || '/data';
const ATTACH_FILE = path.join(STATE_DIR, 'bot-attachments.json');
const SETTINGS_FILE = path.join(STATE_DIR, 'bot-settings.json');
let _stateLoaded = false;

/** `${connectionId}::${botId}` -> { key: value } — OVERRIDES only, never the resolved set. Storing
 *  resolved values would freeze a bot's defaults at the moment an operator first opened the panel. */
const _settings = new Map();
const _settingsKey = (connectionId, botId) => `${connectionId}::${botId}`;

/** Sync on purpose: attachedTo() is called synchronously from the /api/accounts route, and a promise
 *  here would make the roster's bot column race the response. One small file, read once per process. */
function _loadState() {
  if (_stateLoaded) return;
  _stateLoaded = true;
  try {
    const raw = JSON.parse(fs.readFileSync(ATTACH_FILE, 'utf8'));
    for (const [cid, bid] of Object.entries(raw.attachments || {})) {
      if (typeof bid === 'string') _attached.set(cid, bid);
    }
  } catch {
    // Missing file is the normal first-boot state, not an error: it means "nobody has chosen yet",
    // which is precisely when DEFAULT_ATTACHMENTS should speak.
  }
  try {
    const raw = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
    for (const [k, v] of Object.entries(raw.settings || {})) {
      if (v && typeof v === 'object') _settings.set(k, v);
    }
  } catch { /* same — no overrides yet means every bot runs on its declared defaults */ }
}

function _writeJson(file, payload, what) {
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(payload), 'utf8');
    fs.renameSync(tmp, file);
  } catch (e) {
    // A read-only volume must not take the service down — but it MUST be loud, because the symptom
    // otherwise is "my choice keeps reverting" with nothing in the logs.
    console.error(`[bot-runtime] could not persist ${what}:`, e.message);
  }
}

function _saveState() {
  _writeJson(ATTACH_FILE, { attachments: Object.fromEntries(_attached) }, 'attachments');
}

function _saveSettings() {
  _writeJson(SETTINGS_FILE, { settings: Object.fromEntries(_settings) }, 'bot settings');
}

/**
 * A bot is a DIRECTORY with an index.js. Files sitting next to this one (intent.js, README.md) are
 * therefore not candidates and cannot be loaded by accident — the folder convention IS the registry,
 * so adding a bot is `mkdir` and nothing else. No central list to forget to update.
 */
function loadBots(dir = __dirname, { force = false } = {}) {
  if (_bots && !force && _loadedFrom === dir) return _bots;
  const found = new Map();
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (e) {
    console.error('[bot-runtime] cannot read bots dir', dir, e.message);
  }
  for (const ent of entries) {
    if (!ent.isDirectory()) continue;
    const entry = path.join(dir, ent.name, 'index.js');
    if (!fs.existsSync(entry)) continue;
    let mod;
    try {
      // Required one at a time inside try/catch so ONE broken bot cannot stop the service from
      // dispatching to the others — the same reasoning the adapter layer uses for its backends.
      mod = require(entry);
    } catch (e) {
      console.error(`[bot-runtime] bot "${ent.name}" failed to load:`, e.message);
      continue;
    }
    const bad = validate(mod, ent.name);
    if (bad) { console.error(`[bot-runtime] bot "${ent.name}" rejected: ${bad}`); continue; }
    if (found.has(mod.id)) { console.error(`[bot-runtime] duplicate bot id "${mod.id}" (${ent.name}) — skipped`); continue; }
    found.set(mod.id, mod);
  }
  _bots = found;
  _loadedFrom = dir;
  return _bots;
}

/** @returns {string|null} the reason it is not a bot, or null if it is one. */
function validate(mod, folder) {
  if (!mod || typeof mod !== 'object') return 'module export is not an object';
  if (typeof mod.id !== 'string' || !mod.id) return 'missing string `id`';
  if (typeof mod.onMessage !== 'function') return 'missing async `onMessage(msg, ctx)`';
  if (mod.id !== folder) return `id "${mod.id}" does not match folder "${folder}"`;
  // Rejected at LOAD time, not when an operator first opens the settings panel: a schema that cannot
  // be rendered is a broken bot, and finding out about it mid-conversation is far worse.
  const badSchema = validateSchema(mod.settings);
  if (badSchema) return badSchema;
  return null;
}

/** The roster, `none` first — the shape `listBots` advertises to the UI (sim: GET api/bots). */
function listBots(dir) {
  const bots = loadBots(dir);
  return [
    { ...NO_BOT },
    ...[...bots.values()].map((b) => ({
      id: b.id,
      name: b.name || b.id,
      desc: b.desc || '',
      accepts: { ...intent.DEFAULT_ACCEPTS, ...(b.accepts || {}) },
      /** The schema only — VALUES are per connection and come from GET /api/bots/:id/settings, because
       *  this roster is not scoped to a connection and would have to lie about which one it meant. */
      settings: Array.isArray(b.settings) ? b.settings : [],
    })),
  ];
}

function getBot(botId, dir) {
  if (!botId || botId === NO_BOT.id) return null;
  return loadBots(dir).get(botId) || null;
}

// ── attachment ────────────────────────────────────────────────────────────────
/**
 * ONE bot per connection. Not a list: two bots on one conversation means two answers to one question,
 * and no ordering rule makes that read as anything but a broken service. If a connection needs several
 * behaviours, that is one bot with several branches — which is exactly what hacohen-bot is.
 */
function attach(connectionId, botId, dir) {
  if (!connectionId) throw new Error('attach: connectionId required');
  if (botId && botId !== NO_BOT.id && !getBot(botId, dir)) {
    throw new Error(`attach: unknown bot "${botId}"`);
  }
  _loadState();
  // `none` is stored EXPLICITLY rather than by deleting the key: an absent key means "never chosen"
  // and falls through to the protocol default, so deleting would make "turn the bot off" undo itself
  // on the next read.
  const chosen = (!botId || botId === NO_BOT.id) ? NO_BOT.id : botId;
  _attached.set(connectionId, chosen);
  _saveState();
  return chosen;
}

/** Detach == attach('none'). Kept as its own verb because "turn it off" is what the operator means. */
function detach(connectionId) { return attach(connectionId, NO_BOT.id); }

/**
 * Which bot answers on this connection: the operator's explicit choice, else the protocol default,
 * else nothing.
 *
 * Defaults are resolved HERE rather than seeded at load time because a WhatsApp connection id is not
 * knowable until the operator adds the account — see DEFAULT_ATTACHMENTS. An explicit `none` still
 * wins over the default, which is what makes turning a bot off stick.
 */
function attachedTo(connectionId, dir) {
  _loadState();
  const explicit = _attached.get(connectionId);
  if (explicit) return explicit;
  const fallback = DEFAULT_ATTACHMENTS[protocolOf(connectionId)];
  return (fallback && loadBots(dir).has(fallback)) ? fallback : NO_BOT.id;
}

/** Alias matching the canonical op name in the chat-service plan (`setBot`). */
const setBot = attach;

// ── settings ──────────────────────────────────────────────────────────────────
/**
 * A bot declares its own knobs; the runtime stores and validates them and knows nothing about what
 * any of them mean.
 *
 * Settings are per (connection, bot), not per bot. The same bot answering a public WhatsApp number and
 * an internal local chat is doing two different jobs, and a single daily cap or group gate across both
 * is wrong in whichever direction it is set.
 *
 * Supported types are deliberately few — `boolean`, `number`, `text`, `select` — because every type
 * added here is a control the UI must render and a coercion this file must get right.
 */
const SETTING_TYPES = ['boolean', 'number', 'text', 'select'];

/** @returns {Array} the declared schema, always an array (a bot with no settings declares none). */
function settingsSchema(botId, dir) {
  const bot = getBot(botId, dir);
  return (bot && Array.isArray(bot.settings)) ? bot.settings : [];
}

/** @returns {string|null} why this schema is unusable, or null. Used by validate() so a bot with a
 *  malformed schema is rejected at LOAD time rather than when an operator first opens the panel. */
function validateSchema(schema) {
  if (schema === undefined) return null;
  if (!Array.isArray(schema)) return '`settings` must be an array';
  const seen = new Set();
  for (const f of schema) {
    if (!f || typeof f !== 'object') return 'a setting is not an object';
    if (typeof f.key !== 'string' || !f.key) return 'a setting has no string `key`';
    if (seen.has(f.key)) return `duplicate setting key "${f.key}"`;
    seen.add(f.key);
    if (!SETTING_TYPES.includes(f.type)) return `setting "${f.key}" has unknown type "${f.type}"`;
    if (f.type === 'select' && !Array.isArray(f.options)) return `select "${f.key}" has no options`;
  }
  return null;
}

/**
 * Force one submitted value into the declared type, or reject it.
 *
 * Values arrive from an HTTP body, so a number is usually a string and a checkbox is whatever the
 * client felt like sending. Coercing here — once, centrally — is what lets a bot read `settings.x`
 * and trust the type without defending itself.
 *
 * @returns {{ok:true, value:*}|{ok:false, error:string}}
 */
function coerceSetting(field, raw) {
  switch (field.type) {
  case 'boolean':
    if (typeof raw === 'boolean') return { ok: true, value: raw };
    if (raw === 'true' || raw === 'false') return { ok: true, value: raw === 'true' };
    return { ok: false, error: `"${field.key}" must be true or false` };
  case 'number': {
    const n = typeof raw === 'number' ? raw : Number(String(raw).trim());
    if (!Number.isFinite(n)) return { ok: false, error: `"${field.key}" must be a number` };
    if (field.min !== undefined && n < field.min) return { ok: false, error: `"${field.key}" must be at least ${field.min}` };
    if (field.max !== undefined && n > field.max) return { ok: false, error: `"${field.key}" must be at most ${field.max}` };
    return { ok: true, value: n };
  }
  case 'select': {
    const v = String(raw);
    const allowed = field.options.map((o) => String(o && o.value !== undefined ? o.value : o));
    if (!allowed.includes(v)) return { ok: false, error: `"${field.key}" must be one of ${allowed.join(', ')}` };
    return { ok: true, value: v };
  }
  case 'text':
  default: {
    const s = raw === null || raw === undefined ? '' : String(raw);
    if (field.maxLength && s.length > field.maxLength) return { ok: false, error: `"${field.key}" is longer than ${field.maxLength}` };
    return { ok: true, value: s };
  }
  }
}

/** Declared defaults overlaid with the operator's saved overrides. This is what a bot actually runs
 *  on, and the only shape any caller should ever see. */
function getSettings(connectionId, botId, dir) {
  _loadState();
  const out = {};
  for (const f of settingsSchema(botId, dir)) out[f.key] = f.default;
  const saved = _settings.get(_settingsKey(connectionId, botId)) || {};
  for (const [k, v] of Object.entries(saved)) {
    if (k in out) out[k] = v;   // a key no longer in the schema is dropped, not resurrected
  }
  return out;
}

/**
 * Save a PARTIAL set of overrides. Unknown keys are refused rather than ignored: a typo silently
 * accepted is a setting the operator believes they changed and did not.
 *
 * @returns {{ok:true, settings:object}|{ok:false, error:string}}
 */
function setSettings(connectionId, botId, values, dir) {
  if (!connectionId) return { ok: false, error: 'connectionId required' };
  if (!getBot(botId, dir)) return { ok: false, error: `unknown bot "${botId}"` };
  const schema = settingsSchema(botId, dir);
  if (!schema.length) return { ok: false, error: `bot "${botId}" declares no settings` };
  if (!values || typeof values !== 'object') return { ok: false, error: 'settings body must be an object' };

  _loadState();
  const key = _settingsKey(connectionId, botId);
  const next = { ...(_settings.get(key) || {}) };
  for (const [k, raw] of Object.entries(values)) {
    const field = schema.find((f) => f.key === k);
    if (!field) return { ok: false, error: `unknown setting "${k}"` };
    const r = coerceSetting(field, raw);
    if (!r.ok) return r;
    next[k] = r.value;
  }
  _settings.set(key, next);
  _saveSettings();
  return { ok: true, settings: getSettings(connectionId, botId, dir) };
}

/**
 * Drop overrides so the declared DEFAULTS take over again.
 *
 * This is a separate operation and not a PUT of the default values, because the store holds
 * OVERRIDES only (see getSettings): writing the current default back would freeze it forever, so a
 * bot that later changes its own default would keep running the old one on every connection an
 * operator had ever "reset". Deleting the key is the only way to say "follow the bot".
 *
 * `keys` resets those fields; omitting it resets the whole (connection, bot) pair.
 *
 * @returns {{ok:true, settings:object, cleared:string[]}|{ok:false, error:string}}
 */
function clearSettings(connectionId, botId, keys = null, dir) {
  if (!connectionId) return { ok: false, error: 'connectionId required' };
  if (!getBot(botId, dir)) return { ok: false, error: `unknown bot "${botId}"` };
  const schema = settingsSchema(botId, dir);
  if (!schema.length) return { ok: false, error: `bot "${botId}" declares no settings` };
  if (keys !== null && !Array.isArray(keys)) return { ok: false, error: 'keys must be an array' };

  _loadState();
  const key = _settingsKey(connectionId, botId);
  const saved = _settings.get(key) || {};
  let cleared = [];
  if (keys === null) {
    cleared = Object.keys(saved);
    _settings.delete(key);
  } else {
    for (const k of keys) {
      // Same rule setSettings applies: an unknown key is refused, not ignored. "I reset that" and
      // "I typoed that" must not look identical to the operator.
      if (!schema.some((f) => f.key === k)) return { ok: false, error: `unknown setting "${k}"` };
    }
    const next = { ...saved };
    for (const k of keys) if (k in next) { delete next[k]; cleared.push(k); }
    if (Object.keys(next).length) _settings.set(key, next); else _settings.delete(key);
  }
  // Written even when nothing was cleared — a no-op reset must still leave the file consistent with
  // memory, and the caller gets `cleared: []` rather than a failure it cannot act on.
  _saveSettings();
  return { ok: true, cleared, settings: getSettings(connectionId, botId, dir) };
}

/** Test seam: forget every discovered bot, attachment and setting, INCLUDING the persisted ones
 *  already read into memory. Does not delete the files — point CHAT_STATE_DIR at a temp dir in tests. */
function reset() {
  _bots = null; _loadedFrom = null; _stateLoaded = false;
  _attached.clear(); _settings.clear();
}

// ── ctx construction ──────────────────────────────────────────────────────────
/**
 * Split long text the way a transport with a message cap needs it.
 *
 * This is in the RUNTIME, not in the transport, because "your reply was 40 KB" is a bot problem on
 * every backend — WhatsApp truncates around 4096, Telegram at 4096, and a local chat bubble that long
 * is unreadable regardless of whether the store accepts it. A transport that has a better answer can
 * still override it via `transport.sendLong`.
 */
async function chunkedSend(send, text, { chunkSize = 3800, delayMs = 400 } = {}) {
  if (!text) return 0;
  const chunks = [];
  let remaining = String(text);
  while (remaining.length > chunkSize) {
    let cut = remaining.lastIndexOf('\n', chunkSize);
    if (cut < chunkSize * 0.5) cut = chunkSize; // no nearby newline — hard cut
    chunks.push(remaining.slice(0, cut));
    remaining = remaining.slice(cut).replace(/^\n+/, '');
  }
  if (remaining.length > 0) chunks.push(remaining);
  for (let i = 0; i < chunks.length; i++) {
    const header = chunks.length > 1 ? `(${i + 1}/${chunks.length})\n` : '';
    await send(header + chunks[i]);
    if (i < chunks.length - 1 && delayMs) await new Promise((r) => setTimeout(r, delayMs));
  }
  return chunks.length;
}

/**
 * Build the ctx a bot is handed.
 *
 * The FLOOR is `backend.sendMessage(conversationId, {text})` — the one canonical op every backend in
 * chatapi/adapters must implement. Everything else is either derived from it (send/sendLong/sendMenu)
 * or an OPTIONAL transport nicety that degrades to a no-op (react/typing). A bot may therefore call
 * `ctx.react()` unconditionally: on WhatsApp it puts an emoji on the message, on a backend without
 * reactions it costs nothing and changes nothing. Making those mandatory would have blocked Telegram
 * and local chat; making the bot check first would have put transport branching back in the bot,
 * which is the exact thing this stage exists to remove.
 */
function buildCtx(msg, { bot, connectionId, backend, transport = {}, settings = {} }) {
  const conversationId = msg.conversationId;
  const send = async (text, opts = {}) => {
    if (text === null || text === undefined || text === '') return null;
    // `botId` tags this as BOT output. A backend that does not know the field ignores it; the local
    // engine stores it, and its receive path then refuses to dispatch on it — which is what stops
    // two bot-bearing identities answering each other forever.
    return backend.sendMessage(conversationId, { text: String(text), botId: bot.id, ...opts });
  };
  const capabilities = new Set(['send', 'sendLong', 'sendMenu', 'sendTo']);
  if (typeof transport.react === 'function') capabilities.add('react');
  if (typeof transport.typing === 'function') capabilities.add('typing');

  return {
    bot: { id: bot.id, name: bot.name || bot.id },
    connectionId,
    conversationId,
    /** This bot's knobs ON THIS CONNECTION, already defaulted and type-coerced. A bot reads
     *  `ctx.settings.x` and trusts the type; it never reaches for the store itself, so the same bot
     *  can run with different policy on WhatsApp and on local chat without knowing that it does. */
    settings,
    isGroup: Boolean(msg.isGroup),
    sender: msg.sender,
    intent: intent.classify(msg),
    /** The abstract backend itself — the escape hatch for ops a bot legitimately needs
     *  (markRead, listConversations). Still transport-FREE: it is the adapter interface, not a socket. */
    backend,

    send,
    sendLong: (text, opts) => (typeof transport.sendLong === 'function'
      ? transport.sendLong(conversationId, text, opts)
      : chunkedSend(send, text, opts)),
    /**
     * A menu. `text` is the rendered fallback (and is what every transport uses today); `options` is
     * the structured form for backends that have native quick replies. Bots supply both when they can,
     * so a Telegram keyboard is a transport upgrade rather than a bot rewrite.
     */
    sendMenu: ({ text, options } = {}) => (typeof transport.sendMenu === 'function'
      ? transport.sendMenu(conversationId, { text, options })
      : send(text)),
    /** Reply into a DIFFERENT conversation — "that is a DM-only action, go to the DM", broadcasts. */
    sendTo: (otherConversationId, text, opts = {}) =>
      backend.sendMessage(otherConversationId, { text: String(text), botId: bot.id, ...opts }),

    react: async (emoji) => { try { return transport.react ? await transport.react(msg, emoji) : null; } catch { return null; } },
    typing: async (on) => { try { return transport.typing ? await transport.typing(msg, on) : null; } catch { return null; } },
    can: (capability) => capabilities.has(capability),
    log: (...args) => console.log(`[${bot.id}@${connectionId}]`, ...args),
  };
}

// ── dispatch ──────────────────────────────────────────────────────────────────
/**
 * Deliver one normalised inbound message to whichever bot is attached to `connectionId`.
 *
 * Returns a verdict instead of throwing or silently returning: a caller (and a test) has to be able to
 * tell "no bot attached" from "the bot chose not to answer" from "the bot answered", and in a chat
 * window all three look the same.
 *
 * @param {object} msg    normalised inbound message (see README.md)
 * @param {{connectionId:string, backend:object, transport?:object, botsDir?:string}} opts
 * @returns {Promise<{handled:boolean, reason:string, botId:string|null}>}
 */
async function dispatch(msg, { connectionId, backend, transport = {}, botsDir } = {}) {
  if (!msg || !msg.conversationId) return { handled: false, reason: 'not_a_message', botId: null };
  // Every transport echoes what we ourselves sent. Without this the bot answers its own replies, and
  // because each reply is longer than the last it does so forever.
  if (msg.fromMe) return { handled: false, reason: 'from_me', botId: null };
  if (!backend || typeof backend.sendMessage !== 'function') {
    return { handled: false, reason: 'no_backend', botId: null };
  }

  const botId = attachedTo(connectionId);
  const bot = getBot(botId, botsDir);
  if (!bot) return { handled: false, reason: 'no_bot', botId: null };

  const settings = getSettings(connectionId, bot.id, botsDir);

  // A setting whose key is `accepts.<gate>` overrides that gate for this connection. It is a naming
  // CONVENTION rather than two hard-coded keys, so a future gate needs no change here — and it is why
  // an operator can silence a bot in groups on the WhatsApp number while leaving local chat alone,
  // which previously meant editing the bot's manifest and redeploying.
  const accepts = { ...(bot.accepts || {}) };
  for (const [k, v] of Object.entries(settings)) {
    if (k.startsWith('accepts.')) accepts[k.slice('accepts.'.length)] = v;
  }

  const gate = intent.shouldAutoReply(msg, accepts);
  if (!gate.ok) return { handled: false, reason: gate.reason, botId: bot.id };

  const ctx = buildCtx(msg, { bot, connectionId, backend, transport, settings });

  // Serialise per SENDER, not per conversation: subscriber state ("I am waiting for your balance
  // sheet") is a property of the person, and the same person can be typing in a group and a DM at
  // once. Keying the lock on the conversation would let those two race on one state machine.
  const lockKey = `${connectionId}:${(msg.sender && msg.sender.id) || msg.conversationId}`;
  try {
    await runExclusive(lockKey, async () => { await bot.onMessage(msg, ctx); });
    return { handled: true, reason: 'ok', botId: bot.id };
  } catch (e) {
    console.error(`[bot-runtime] ${bot.id} threw on ${connectionId}:`, e);
    return { handled: false, reason: 'bot_error', botId: bot.id, error: e };
  }
}

module.exports = {
  // discovery
  loadBots, listBots, getBot, validate, NO_BOT, DEFAULT_ATTACHMENTS, protocolOf,
  // attachment
  attach, detach, attachedTo, setBot, reset,
  // settings
  settingsSchema, validateSchema, coerceSetting, getSettings, setSettings, clearSettings, SETTING_TYPES,
  // dispatch
  dispatch, buildCtx, chunkedSend,
};
