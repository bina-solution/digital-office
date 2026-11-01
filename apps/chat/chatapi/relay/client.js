/**
 * ONE AUTHENTICATED SOCKET PER PROFILE — the transport `adapters/buzz.js` runs on.
 *
 * The relay's protocol is NIP-01 over a websocket (EVENT / REQ / CLOSE / AUTH) plus an HTTP bridge
 * for the same ingest path, Blossom media and NIP-45 counts. Block's own desktop client uses
 * nothing else, so this is the whole surface — there is no richer REST API to reach for. Every
 * recipe here is the one `chatapi/relay/probe.mjs` proved 8/8 against the pinned image.
 *
 * ── WHY A SOCKET AND NOT JUST HTTP ───────────────────────────────────────────────────────────
 * The abstract API is request/response, so most ops could be plain HTTP. Two things force a live
 * socket, and they are the reason this class is stateful at all:
 *
 *   presence + typing   kinds 20000-29999 are EPHEMERAL — the relay fans them out and does not
 *                       store them. `listConversations()` returns `online` and `typing` per row,
 *                       and the only way to answer those is to have been listening. So the client
 *                       keeps a subscription and a small in-memory cache with a TTL.
 *   the receive path    local_inbox.js dispatches bots off `backend.subscribe()`. On postgres that
 *                       was LISTEN/NOTIFY; here it is a REQ that stays open.
 *
 * That makes this the same class of object as the Baileys socket the app already holds, and it is
 * cached the same way — by CREDENTIAL fingerprint in adapters/index.js, so a rotated key rebuilds
 * it without a restart and `close()` tears the old one down.
 *
 * ── RECONNECTION IS NOT OPTIONAL ─────────────────────────────────────────────────────────────
 * A dropped socket must not silently become "nobody is online and no bot ever answers again". The
 * client reconnects with backoff, re-authenticates, and REPLAYS its persistent subscriptions —
 * without that last part a reconnect looks healthy and delivers nothing, which is the failure mode
 * the mail read-pool leak taught (a pool slot destroyed on a failed connect never came back).
 */
const crypto = require('crypto');
const { finalizeEvent } = require('nostr-tools/pure');

const { secretBytes, pubkeyOf } = require('./identity');

const OP_TIMEOUT_MS = Number(process.env.CHAT_RELAY_OP_TIMEOUT_MS || 20000);
const RECONNECT_MAX_MS = 30000;
/** How long an ephemeral presence/typing signal is believed after it arrives. The relay does not
 *  store them, so this is the only definition of "still true". */
const PRESENCE_TTL_MS = Number(process.env.CHAT_PRESENCE_TTL_MS || 90000);
const TYPING_TTL_MS = Number(process.env.CHAT_TYPING_TTL_MS || 9000);

const KIND = {
  PROFILE: 0, DELETION: 5, REACTION: 7, STREAM_MESSAGE: 9,
  NIP29_PUT_USER: 9000, NIP29_REMOVE_USER: 9001, NIP29_CREATE_GROUP: 9007,
  PIN_LIST: 10001, MEMBERSHIP: 13534,
  AUTH: 22242, BLOSSOM_AUTH: 24242, HTTP_AUTH: 27235,
  READ_STATE: 30078,
  GROUP_METADATA: 39000, GROUP_MEMBERS: 39002,
  PRESENCE: 20001, TYPING: 20002,
  STREAM_MESSAGE_V2: 40002, STREAM_MESSAGE_EDIT: 40003, SYSTEM_MESSAGE: 40099,
  PRESENCE_SNAPSHOT: 40902,
  DM_CREATED: 41001, DM_OPEN: 41010,
};
/**
 * TWO lists, because a thread and a badge are asking different questions.
 *
 * MESSAGE_KINDS is what a PERSON said. TIMELINE_KINDS adds the relay's own system events ("member
 * joined", "topic changed"), which belong in an open conversation but not in a count of things you
 * have not read — creating a group and adding one member emits several of them, so counting the
 * timeline made a two-message conversation show `unread: 4` (measured against the live relay).
 *
 * Each is kept as ONE constant so a query and its live subscription can never disagree about what
 * they are watching.
 */
const MESSAGE_KINDS = [KIND.STREAM_MESSAGE, KIND.STREAM_MESSAGE_V2];
const TIMELINE_KINDS = [...MESSAGE_KINDS, KIND.SYSTEM_MESSAGE];

class RelayError extends Error {
  constructor(message, status = 502) { super(message); this.name = 'RelayError'; this.status = status; }
}

class RelayClient {
  /**
   * @param {object} opts
   * @param {string} opts.nsec      the profile's 32-byte hex secret key
   * @param {string} [opts.wsUrl]   ws://chat-relay:3000 — must match the relay's own RELAY_URL
   *                                authority, because the community is bound from the Host header
   *                                and fails closed on a mismatch.
   */
  constructor({ nsec, wsUrl, httpUrl } = {}) {
    this.sk = secretBytes(nsec);
    this.pubkey = pubkeyOf(nsec);
    this.wsUrl = wsUrl || process.env.CHAT_RELAY_WS || 'ws://chat-relay:3000';
    this.httpUrl = httpUrl || process.env.CHAT_RELAY_HTTP || this.wsUrl.replace(/^ws/, 'http');
    this.ws = null;
    this.authed = false;
    this.closed = false;
    this.connecting = null;
    this.backoff = 1000;
    this.subs = new Map();        // sub id -> { filter, onEvent, persistent, buf, resolve, timer }
    this.oks = new Map();         // event id -> resolver
    this.presence = new Map();    // pubkey -> at (ms)
    this.typing = new Map();      // `${channel}:${pubkey}` -> at (ms)
    this.lastError = null;
  }

  // ── connection ────────────────────────────────────────────────────────────────────────────────

  async connect() {
    if (this.closed) throw new RelayError('client is closed', 503);
    if (this.authed && this.ws && this.ws.readyState === 1) return this;
    if (this.connecting) return this.connecting;
    this.connecting = new Promise((resolve, reject) => {
      let settled = false;
      const done = (fn, arg) => { if (!settled) { settled = true; this.connecting = null; fn(arg); } };
      let ws;
      try { ws = new WebSocket(this.wsUrl); } catch (e) { return done(reject, new RelayError(`relay unreachable: ${e.message}`, 503)); }
      this.ws = ws;
      const timer = setTimeout(() => done(reject, new RelayError('relay auth timed out', 504)), OP_TIMEOUT_MS);
      ws.onerror = () => { clearTimeout(timer); done(reject, new RelayError('relay socket error', 503)); };
      ws.onclose = () => {
        clearTimeout(timer);
        this.authed = false;
        done(reject, new RelayError('relay closed the socket', 503));
        this._scheduleReconnect();
      };
      ws.onmessage = (raw) => {
        let m; try { m = JSON.parse(raw.data); } catch { return; }
        this._handle(m, { timer, done, resolve });
      };
    });
    return this.connecting;
  }

  _handle(m, ctx) {
    const [type] = m;
    if (type === 'AUTH' && typeof m[1] === 'string') {
      // NIP-42. The relay answers OK on the auth event's OWN id — that, not the socket being open,
      // is what "authenticated" means.
      const ev = this._sign({ kind: KIND.AUTH, tags: [['relay', this.wsUrl], ['challenge', m[1]]], content: '' });
      this.authId = ev.id;
      this._send(['AUTH', ev]);
      return;
    }
    if (type === 'OK') {
      const [, id, ok, msg] = m;
      if (id === this.authId) {
        if (ctx) clearTimeout(ctx.timer);
        this.authed = Boolean(ok);
        this.backoff = 1000;
        if (!ok) { this.lastError = `relay rejected auth: ${msg}`; return ctx && ctx.done(ctx.resolve, this); }
        this._replaySubs();
        return ctx && ctx.done(ctx.resolve, this);
      }
      const w = this.oks.get(id);
      if (w) { this.oks.delete(id); w({ ok, msg }); }
      return;
    }
    if (type === 'EVENT') {
      const s = this.subs.get(m[1]);
      if (!s) return;
      this._observe(m[2]);
      if (s.persistent) { try { s.onEvent(m[2]); } catch (e) { console.error('[chat/relay] subscriber threw:', e.message); } }
      else s.buf.push(m[2]);
      return;
    }
    if (type === 'EOSE' || type === 'CLOSED') {
      const s = this.subs.get(m[1]);
      if (s && !s.persistent) s.finish();
      return;
    }
    if (type === 'NOTICE') { this.lastError = String(m[1] || ''); }
  }

  /** Every event that arrives feeds the ephemeral caches, whichever subscription carried it. */
  _observe(ev) {
    if (!ev) return;
    if (ev.kind === KIND.PRESENCE || ev.kind === KIND.PRESENCE_SNAPSHOT) {
      this.presence.set(ev.pubkey, Date.now());
    } else if (ev.kind === KIND.TYPING) {
      const h = (ev.tags || []).find((t) => t[0] === 'h');
      if (h) this.typing.set(`${h[1]}:${ev.pubkey}`, Date.now());
    }
  }

  _scheduleReconnect() {
    if (this.closed || this._reconnectTimer) return;
    const wait = this.backoff;
    this.backoff = Math.min(this.backoff * 2, RECONNECT_MAX_MS);
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect().catch(() => { /* onclose schedules the next attempt */ });
    }, wait);
    if (this._reconnectTimer.unref) this._reconnectTimer.unref();
  }

  /** Re-issue every persistent REQ after a reconnect. Without this a reconnect LOOKS healthy and
   *  delivers nothing: presence stops updating and no bot is ever woken again. */
  _replaySubs() {
    for (const [id, s] of this.subs) if (s.persistent) this._send(['REQ', id, s.filter]);
  }

  _send(frame) {
    if (!this.ws || this.ws.readyState !== 1) throw new RelayError('relay socket is not open', 503);
    this.ws.send(JSON.stringify(frame));
  }

  _sign(tmpl) {
    return finalizeEvent({ created_at: Math.floor(Date.now() / 1000), tags: [], content: '', ...tmpl }, this.sk);
  }

  // ── the four primitives ───────────────────────────────────────────────────────────────────────

  /** Publish a signed event; resolves only on the relay's OK. A rejected event REJECTS — "a write
   *  that did not happen never reports success". */
  async publish(tmpl) {
    await this.connect();
    const ev = this._sign(tmpl);
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => { this.oks.delete(ev.id); reject(new RelayError(`relay did not answer for kind ${tmpl.kind}`, 504)); }, OP_TIMEOUT_MS);
      this.oks.set(ev.id, (r) => {
        clearTimeout(t);
        if (!r.ok) return reject(new RelayError(`relay rejected kind ${tmpl.kind}: ${r.msg}`, 502));
        resolve(ev);
      });
      try { this._send(['EVENT', ev]); } catch (e) { clearTimeout(t); this.oks.delete(ev.id); reject(e); }
    });
  }

  /** One-shot query: REQ until EOSE. `filters` may be one filter or several — several in ONE REQ is
   *  what makes "the newest message in each of N channels" a single round trip instead of N. */
  async query(filters) {
    await this.connect();
    const list = Array.isArray(filters) ? filters : [filters];
    const id = 'q' + crypto.randomBytes(6).toString('hex');
    return new Promise((resolve, reject) => {
      const sub = { filter: list[0], persistent: false, buf: [] };
      const t = setTimeout(() => { this.subs.delete(id); reject(new RelayError('relay query timed out', 504)); }, OP_TIMEOUT_MS);
      sub.finish = () => {
        clearTimeout(t);
        this.subs.delete(id);
        try { this._send(['CLOSE', id]); } catch { /* socket already gone */ }
        resolve(sub.buf);
      };
      this.subs.set(id, sub);
      try { this._send(['REQ', id, ...list]); } catch (e) { clearTimeout(t); this.subs.delete(id); reject(e); }
    });
  }

  /**
   * A live REQ that stays open. Returns an unsubscribe.
   *
   * ── FILTERS HERE MUST BE BARE: no `since`, no `limit` ────────────────────────────────────────
   * Measured against the live relay with chatapi/relay/subcheck.mjs, three filters differing only
   * in that respect:
   *
   *   {kinds:[39002], '#p':[me]}              -> 2 live events   ✅
   *   {kinds:[39002], '#p':[me], since: t}    -> 0               ❌
   *   {kinds:[39002], '#p':[me], limit: 0}    -> 0               ❌
   *
   * So the relay treats a filter carrying either as a HISTORICAL request and its live fan-out never
   * matches it again. That is the opposite of the obvious reading — `limit: 0` looks like "live
   * only", and it is what the reference web client uses for presence — and it is why the bot
   * answered nothing and presence never updated: both subscriptions were syntactically fine and
   * permanently silent.
   *
   * The consequence is that a bare filter REPLAYS history on subscribe, so the caller must gate on
   * `created_at` itself. `sinceMs` does that here rather than leaving every caller to remember it —
   * without it a bot wakes up and answers every message it has ever received.
   */
  async subscribe(filters, onEvent, { sinceMs = null } = {}) {
    await this.connect();
    const list = (Array.isArray(filters) ? filters : [filters]).map((f) => {
      const { since, until, limit, ...bare } = f;
      return bare;
    });
    const floor = sinceMs === null ? null : Math.floor(sinceMs / 1000);
    const deliver = onEvent;
    onEvent = (ev) => { if (floor === null || ev.created_at >= floor) deliver(ev); };
    const id = 's' + crypto.randomBytes(6).toString('hex');
    this.subs.set(id, { filter: list[0], filters: list, persistent: true, onEvent, buf: [] });
    this._send(['REQ', id, ...list]);
    return async () => {
      this.subs.delete(id);
      try { this._send(['CLOSE', id]); } catch { /* already gone */ }
    };
  }

  /** NIP-45 count over the HTTP bridge. Used for unread, where fetching the events to length them
   *  would mean pulling every unread message of every conversation just to render a badge. */
  async count(filter) {
    const r = await this._http('POST', '/count', { body: JSON.stringify([filter]) });
    const n = r && (r.count ?? (Array.isArray(r) ? r[0] && r[0].count : null));
    return Number.isFinite(Number(n)) ? Number(n) : null;
  }

  // ── HTTP bridge (NIP-98) + media (Blossom) ────────────────────────────────────────────────────

  async _http(method, path, { body = null, headers = {} } = {}) {
    const url = this.httpUrl + path;
    // The `payload` tag is the sha256 of the request body, and NIP-98 defines it for exactly the
    // reason it is load-bearing here: WITHOUT it, two POSTs to the same path in the same second
    // sign a byte-identical event — same kind, same created_at, same u/method tags — which has the
    // same event id, and the relay correctly rejects the second as a REPLAY.
    //
    // That is not a hypothetical: listConversations issues two /count calls per conversation
    // (all-since-frontier and mine-since-frontier) concurrently, so every unread badge produced
    // `401 NIP-98: replay detected` and the whole list degraded to empty. The bodies differ, so
    // hashing them makes the two events distinct — and it is what a verifier is entitled to check.
    //
    // The payload hash is necessary but NOT sufficient: two IDENTICAL requests in the same second
    // are still byte-identical events, and /readyz probing on a timer does exactly that. So a
    // random `nonce` makes every auth event unique by construction. Extra tags are permitted — a
    // verifier checks `u`, `method` and `payload` — and this is the only thing that makes the
    // guarantee hold regardless of what the caller does.
    const tags = [['u', url], ['method', method], ['nonce', crypto.randomBytes(16).toString('hex')]];
    if (body) tags.push(['payload', crypto.createHash('sha256').update(body).digest('hex')]);
    const auth = this._sign({ kind: KIND.HTTP_AUTH, tags, content: '' });
    const res = await fetch(url, {
      method,
      body,
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Nostr ' + Buffer.from(JSON.stringify(auth)).toString('base64'),
        ...headers,
      },
    });
    const text = await res.text();
    if (!res.ok) throw new RelayError(`relay ${method} ${path} -> ${res.status}: ${text.slice(0, 200)}`, res.status);
    try { return text ? JSON.parse(text) : null; } catch { return null; }
  }

  /**
   * Blossom upload. Two things here are not guessable and both were found the hard way by
   * chatapi/relay/probe.mjs:
   *   · the auth event is kind 24242 (BUD-11), NOT the 27235 the rest of the bridge uses;
   *   · `X-SHA-256` is a MANDATORY HEADER, and its absence 401s with the generic "authentication
   *     failed" whose real reason only ever appears in the relay's own log.
   */
  async uploadBlob(bytes, { mime = 'application/octet-stream', filename = null } = {}) {
    const buf = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
    const sha = crypto.createHash('sha256').update(buf).digest('hex');
    const exp = String(Math.floor(Date.now() / 1000) + 300);
    const ev = this._sign({
      kind: KIND.BLOSSOM_AUTH,
      tags: [['t', 'upload'], ['x', sha], ['expiration', exp]],
      content: filename ? `Upload ${filename}` : 'Upload',
    });
    const headers = {
      Authorization: 'Nostr ' + Buffer.from(JSON.stringify(ev)).toString('base64'),
      'Content-Type': mime,
      'X-SHA-256': sha,
    };
    let res = await fetch(`${this.httpUrl}/upload`, { method: 'PUT', body: buf, headers });
    if (res.status === 404 || res.status === 405) {
      res = await fetch(`${this.httpUrl}/media/upload`, { method: 'PUT', body: buf, headers });
    }
    const text = await res.text();
    if (!res.ok) throw new RelayError(`media upload -> ${res.status}: ${text.slice(0, 200)}`, res.status);
    const d = JSON.parse(text);
    // THE RELAY'S MIME WINS, not the one we sent. It sniffs the bytes and stores its own verdict,
    // then VALIDATES the `imeta m` tag of any message referencing the blob against it — so echoing
    // our Content-Type back produced `invalid: imeta m (text/plain) does not match stored MIME
    // (application/octet-stream)` and the message was rejected outright, after the upload had
    // already succeeded. Reporting what was stored is the only way the two can agree.
    return {
      sha256: d.sha256 || sha,
      url: d.url || `${this.httpUrl}/media/${sha}`,
      size: Number(d.size) || buf.length,
      mime: d.type || d.mime || mime,
      filename,
    };
  }

  /** Fetch a blob back. Also Blossom-authenticated, verb `get` — this is the call a bot's
   *  `attachment.download()` makes. */
  async downloadBlob(urlOrSha) {
    const raw = String(urlOrSha || '');
    const path = /^https?:\/\//.test(raw) ? new URL(raw).pathname : `/media/${raw}`;
    const sha = (path.split('/').pop() || '').split('.')[0];
    const ev = this._sign({
      kind: KIND.BLOSSOM_AUTH,
      tags: [['t', 'get'], ['x', sha], ['expiration', String(Math.floor(Date.now() / 1000) + 300)]],
      content: 'Download',
    });
    const res = await fetch(this.httpUrl + path, {
      headers: { Authorization: 'Nostr ' + Buffer.from(JSON.stringify(ev)).toString('base64') },
    });
    const body = Buffer.from(await res.arrayBuffer());
    if (!res.ok) throw new RelayError(`media get ${path} -> ${res.status}`, res.status);
    return body;
  }

  // ── ephemeral state, read by the conversation list ───────────────────────────────────────────

  isOnline(pubkey) {
    const at = this.presence.get(pubkey);
    return Boolean(at && Date.now() - at < PRESENCE_TTL_MS);
  }

  isTyping(channelId, pubkey) {
    const at = this.typing.get(`${channelId}:${pubkey}`);
    return Boolean(at && Date.now() - at < TYPING_TTL_MS);
  }

  /** Announce our own presence. Ephemeral, so it is re-sent rather than stored. */
  async announcePresence(status = 'online') {
    try { await this.publish({ kind: KIND.PRESENCE, content: JSON.stringify({ status }) }); }
    catch { /* presence is best-effort by construction */ }
  }

  async close() {
    this.closed = true;
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
    this.subs.clear();
    try { this.ws && this.ws.close(); } catch { /* already gone */ }
    this.ws = null; this.authed = false;
  }
}

module.exports = { RelayClient, RelayError, KIND, MESSAGE_KINDS, TIMELINE_KINDS };
