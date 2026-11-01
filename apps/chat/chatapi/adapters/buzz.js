/**
 * chat_local — the platform's OWN chat, on a buzz relay it runs itself.
 *
 * A peer of the remote backends, not a fallback: users, 1:1 chats, groups + membership, messages,
 * media attachments, mentions and read state, behind the same op surface adapters/index.js
 * dispatches through. A bot written against the abstract API runs here unchanged — which is the
 * whole justification for the engine, and the acceptance test for this file.
 *
 * ── WHY AN ENGINE INSTEAD OF THE TABLES THIS REPLACES ────────────────────────────────────────
 * `chat-service-plan.md` §3 chose to build over the platform's postgres rather than adopt
 * Rocket.Chat / Matrix / Mattermost, because each was a heavyweight PRODUCT that would still need
 * an adapter. buzz is adopted as an ENGINE — the seat docker-mailserver holds for mail_imap_local —
 * and it earns it on the one axis that matters: read state, pin lists, typing, presence, threads,
 * reactions, edits, deletions, group roles, mentions, media and full-text search are all things the
 * seven hand-written tables did not have and would each have been a change here. The full argument,
 * the op mapping and the measured evidence are in ai/context/chat-buzz-engine-plan.md.
 *
 * ── THE ONE THING THAT IS GENUINELY HARDER ───────────────────────────────────────────────────
 * The relay is an append-only signed event log, so a conversation LIST is a projection, not a
 * query. `_listSql`'s single statement with three LATERALs became: rosters, metadata, one
 * multi-filter REQ for the newest message of every channel at once, the read-state event, the peer
 * profiles, the pin list. Batched, but still several round trips where there was one. The
 * projection itself is pure and lives in relay/project.js so it is testable without a relay.
 *
 * DEGRADATION is unchanged and still the contract indox's /sync/registry established: every op
 * passes through `_guard`, so an unreachable relay produces an empty list, an empty thread or an
 * explicit `{ok:false, reachable:false, error}` — never a throw and never a 500. The chat page
 * still renders, probe() is the ONE place that says the engine is down, and A WRITE THAT DID NOT
 * HAPPEN NEVER REPORTS SUCCESS.
 */
const crypto = require('crypto');
const fs = require('fs');

const present = require('../relay/present');
const project = require('../relay/project');
const { RelayClient, KIND, MESSAGE_KINDS, TIMELINE_KINDS } = require('../relay/client');

const PROTOCOL = 'chat_local';
/** The relay caps a filter at 500 historical results; asking for more silently truncates. */
const PAGE = 500;

class BuzzChatBackend {
  /**
   * @param {object} opts
   * @param {string} opts.selfId    the profile slug this backend acts AS
   * @param {string} opts.nsec      its relay identity (from the vault, never from env)
   * @param {object} [opts.profiles] ProfileStore — resolves a pubkey back to a profile slug
   * @param {object} [opts.client]  injected RelayClient (tests)
   */
  constructor(opts = {}) {
    this.selfId = opts.selfId;
    // REQUIRED, for the same reason the postgres backend required it: a backend exists to answer as
    // ONE profile. Without it every message renders as inbound and every query is scoped to nobody.
    if (!this.selfId) throw new Error('BuzzChatBackend needs a selfId — the profile it acts as');
    if (!opts.client && !opts.nsec) throw new Error('BuzzChatBackend needs the profile nsec from the vault');
    this.client = opts.client || new RelayClient({ nsec: opts.nsec });
    this.profiles = opts.profiles || null;
    this.pubkey = this.client.pubkey;
    this.lastError = null;
    this._slugCache = new Map();   // pubkey -> profile slug | null
  }

  get protocol() { return PROTOCOL; }

  /**
   * Announce THIS profile's name to the relay, once per process.
   *
   * kind:0 is what turns a 64-character pubkey into a person in everyone else's client. It is
   * published from here rather than from engine/bootstrap.js because this object already holds an
   * authenticated socket for this exact identity — and because bootstrap must never do network I/O
   * (it is the one path that may not fail the boot). Doing it lazily is also self-healing: a relay
   * that was down when the profile was created gets the name on the profile's next op.
   *
   * Best-effort by construction. kind:0 is replaceable, so re-publishing the same name is a no-op
   * to every reader, and a failure here must cost a display name and nothing else.
   */
  async _ensureSelfMeta() {
    if (this._metaDone) return;
    this._metaDone = true;                      // set FIRST: one attempt per process, never a retry storm
    try {
      const p = this.profiles ? await this.profiles.get(this.selfId).catch(() => null) : null;
      const display = (p && p.display_name) || this.selfId;
      await this.client.publish({
        kind: KIND.PROFILE,
        content: JSON.stringify({ name: display, display_name: display }),
      });
    } catch (e) {
      console.warn(`[chat/buzz] ${this.selfId}: could not publish its name (${e.message})`);
    }
  }

  /** Every relay-touching op goes through here, so degradation is ONE behaviour rather than twelve. */
  async _guard(fn, fallback) {
    try {
      await this._ensureSelfMeta();
      const out = await fn();
      this.lastError = null;
      return out;
    } catch (e) {
      this.lastError = { at: new Date().toISOString(), message: String((e && e.message) || e) };
      console.error('[chat/buzz] degraded:', this.lastError.message);
      return fallback(e);
    }
  }

  /** pubkey -> profile slug, cached. A pubkey with no profile is a CONTACT, not an error. */
  async _slug(pubkey) {
    if (!pubkey) return null;
    if (this._slugCache.has(pubkey)) return this._slugCache.get(pubkey);
    let slug = null;
    if (this.profiles) {
      const p = await this.profiles.byPubkey(pubkey).catch(() => null);
      slug = p ? p.id : null;
    }
    this._slugCache.set(pubkey, slug);
    return slug;
  }

  async _slugSync() {
    // Materialise every profile's pubkey once per list build, so the projection's pubkey->slug
    // lookup is a map read rather than a query per author.
    if (!this.profiles) return (pk) => null;
    const all = await this.profiles.list().catch(() => []);
    const byPk = new Map();
    for (const p of all) if (p.pubkey) { byPk.set(p.pubkey, p.id); this._slugCache.set(p.pubkey, p.id); }
    return (pk) => byPk.get(pk) || null;
  }

  // ── canonical ops ─────────────────────────────────────────────────────────────────────────────

  /**
   * The conversation list.
   *
   * Batched deliberately: the newest message of every channel is ONE multi-filter REQ, not one per
   * channel. Unread is the relay's own /count against my read frontier, because pulling every
   * unread message of every conversation just to length an array is exactly the N+1 the postgres
   * engine's single query existed to avoid.
   */
  async listConversations({ limit = 200 } = {}) {
    return this._guard(async () => {
      const me = this.pubkey;
      // ONE source for "which conversations am I in": the 39002 rosters that name me. A DM is a
      // channel like any other here — it gets the same roster — so there is no second query for
      // them. An earlier version also asked for kind:41001 ("DM created"); the relay never emits
      // that, so it returned nothing and every DM was invisible. See relay/inspect.mjs.
      const [rosters, readEv, pinEv] = await Promise.all([
        this.client.query({ kinds: [KIND.GROUP_MEMBERS], '#p': [me], limit: PAGE }),
        this.client.query({ kinds: [KIND.READ_STATE], authors: [me], '#d': [project.readStateCoord(me)], limit: 1 }),
        this.client.query({ kinds: [KIND.PIN_LIST], authors: [me], limit: 1 }),
      ]);
      const ids = [...new Set(rosters.map((e) => project.tagValue(e, 'd')).filter(Boolean))].slice(0, limit);
      if (!ids.length) return [];

      const frontiers = project.parseReadState(readEv[0]);
      const pinned = new Set(project.tagValues(pinEv[0], 'e').concat(project.tagValues(pinEv[0], 'h')));
      const rosterById = new Map();
      for (const e of rosters) { const d = project.tagValue(e, 'd'); if (d) rosterById.set(d, e); }

      const [meta, lastEvents] = await Promise.all([
        this.client.query({ kinds: [KIND.GROUP_METADATA], '#d': ids, limit: ids.length }),
        // ONE REQ carrying N filters — the newest message of every channel in a single round trip.
        this.client.query(ids.map((id) => ({ kinds: MESSAGE_KINDS, '#h': [id], limit: 1 }))),
      ]);
      const metaById = new Map();
      for (const e of meta) { const c = project.channelFromMetadata(e); if (c) metaById.set(c.id, c); }
      const lastById = new Map();
      for (const e of lastEvents) {
        const h = project.channelOf(e);
        if (!h) continue;
        const cur = lastById.get(h);
        if (!cur || e.created_at > cur.created_at) lastById.set(h, e);
      }

      const peers = new Set();
      for (const id of ids) for (const p of project.membersFromRoster(rosterById.get(id))) if (p !== me) peers.add(p);
      const slugOf = await this._slugSync();
      const profileEvents = peers.size
        ? await this.client.query({ kinds: [KIND.PROFILE], authors: [...peers], limit: peers.size })
        : [];
      const byPk = project.profilesFromEvents(profileEvents, slugOf);

      const rows = await Promise.all(ids.map(async (id) => {
        const m = metaById.get(id) || { id, name: '', type: 'stream' };
        const members = project.membersFromRoster(rosterById.get(id));
        // The TYPE decides, not the headcount. A two-person stream channel is still a group (it has
        // its own name, and gaining a third member must not change how it renders), and a DM with a
        // member added is still a DM to the relay.
        const group = m.type !== 'dm';
        const peerPk = group ? null : members.find((p) => p !== me) || null;
        const peer = peerPk ? (byPk[peerPk] || { id: slugOf(peerPk) || peerPk, name: (slugOf(peerPk) || peerPk.slice(0, 8)), handle: '', color: present.colorOf(peerPk) }) : null;
        const last = lastById.get(id) || null;
        const frontier = frontiers[id] || 0;
        let unread = 0;
        if (last && last.created_at > frontier) {
          // count(all since frontier) - count(mine since frontier): /count has no "not authors".
          const [all, mine] = await Promise.all([
            this.client.count({ kinds: MESSAGE_KINDS, '#h': [id], since: frontier + 1 }),
            this.client.count({ kinds: MESSAGE_KINDS, '#h': [id], authors: [me], since: frontier + 1 }),
          ]);
          unread = Math.max(0, (all ?? 0) - (mine ?? 0));
        }
        const outbound = last ? last.pubkey === me : false;
        return present.conversation({
          id,
          group,
          title: m.name,
          tag: group ? 'קבוצה' : '',
          pinned: pinned.has(id),
          peer,
          memberCount: members.length,
          unread,
          online: peerPk ? this.client.isOnline(peerPk) : false,
          typing: peerPk ? this.client.isTyping(id, peerPk) : false,
          last: last ? {
            id: last.id,
            text: last.content,
            fileName: (project.attachmentFromEvent(last) || {}).name || null,
            at: new Date(last.created_at * 1000),
            outbound,
            status: outbound ? project.deliveryStatus(last.created_at, this._peerFrontiers(members, me, frontiers)) : null,
          } : null,
          updatedAt: last ? new Date(last.created_at * 1000) : null,
        });
      }));
      return present.sortConversations(rows);
    }, (e) => present.degradedList(e));
  }

  /** Other members' read frontiers are not readable per-peer without N queries, so an outbound
   *  message reports `sent` unless we already know better. Stated rather than faked. */
  _peerFrontiers() { return {}; }

  async getConversation(id, { limit = PAGE } = {}) {
    return this._guard(async () => {
      const me = this.pubkey;
      const [roster, meta, events, readEv] = await Promise.all([
        this.client.query({ kinds: [KIND.GROUP_MEMBERS], '#d': [id], limit: 1 }),
        this.client.query({ kinds: [KIND.GROUP_METADATA], '#d': [id], limit: 1 }),
        this.client.query({ kinds: TIMELINE_KINDS, '#h': [id], limit }),
        this.client.query({ kinds: [KIND.READ_STATE], authors: [me], '#d': [project.readStateCoord(me)], limit: 1 }),
      ]);
      if (!roster.length && !meta.length && !events.length) return null;   // 404, not "degraded"

      const members = project.membersFromRoster(roster[0]);
      const m = project.channelFromMetadata(meta[0]) || { id, name: '', type: 'stream' };
      const group = m.type !== 'dm';
      const slugOf = await this._slugSync();
      const authors = [...new Set(events.map((e) => e.pubkey).concat(members))];
      const byPk = project.profilesFromEvents(
        authors.length ? await this.client.query({ kinds: [KIND.PROFILE], authors, limit: authors.length }) : [],
        slugOf);
      const peerPk = group ? null : members.find((p) => p !== me) || null;
      const peer = peerPk ? (byPk[peerPk] || { id: slugOf(peerPk) || peerPk, name: slugOf(peerPk) || peerPk.slice(0, 8), handle: '', color: present.colorOf(peerPk) }) : null;
      const frontiers = project.parseReadState(readEv[0]);

      const msgs = events
        .filter(project.isMessage)
        .sort((a, b) => a.created_at - b.created_at || (a.id < b.id ? -1 : 1))
        .map((e) => {
          const outbound = e.pubkey === me;
          return present.message({
            id: e.id,
            outbound,
            text: e.content,
            at: new Date(e.created_at * 1000),
            status: outbound ? project.deliveryStatus(e.created_at, this._peerFrontiers()) : null,
            group,
            sender: byPk[e.pubkey] || { id: slugOf(e.pubkey) || e.pubkey, name: slugOf(e.pubkey) || e.pubkey.slice(0, 8), color: present.colorOf(e.pubkey) },
            attachment: project.attachmentFromEvent(e),
            mentions: project.tagValues(e, 'p').map((p) => slugOf(p) || p),
          });
        });

      return {
        id,
        contact: present.conversation({
          id, group, title: m.name, peer, memberCount: members.length,
          unread: 0, pinned: false,
          online: peerPk ? this.client.isOnline(peerPk) : false,
          typing: peerPk ? this.client.isTyping(id, peerPk) : false,
          last: null, updatedAt: null,
        }),
        messages: msgs,
      };
    }, (e) => ({
      id,
      contact: { id, name: '', handle: '', initials: '??', color: 'var(--muted)', tag: '', group: false },
      messages: [], reachable: false, error: String((e && e.message) || e),
    }));
  }

  /**
   * Send. Mentions are resolved against THIS channel's members — a mention is a notification, and
   * matching against everyone would let a token pull in someone who cannot see the conversation.
   */
  async sendMessage(conversationId, { text = '', mentions = null, attachment = null, botId = null } = {}) {
    return this._guard(async () => {
      const body = String(text || '');
      if (!body.trim() && !attachment) return { ok: false, error: 'a message needs text or an attachment', message: null };

      const [roster, meta] = await Promise.all([
        this.client.query({ kinds: [KIND.GROUP_MEMBERS], '#d': [conversationId], limit: 1 }),
        this.client.query({ kinds: [KIND.GROUP_METADATA], '#d': [conversationId], limit: 1 }),
      ]);
      const chan = project.channelFromMetadata(meta[0]);
      // Membership from the roster, falling back to the metadata's own `p` tags: the relay writes
      // both for a DM, and a roster that has not propagated yet must not read as "no such chat".
      const members = project.membersFromRoster(roster[0]).length
        ? project.membersFromRoster(roster[0])
        : ((chan && chan.members) || []).map((p) => String(p).toLowerCase());
      if (!members.includes(this.pubkey)) {
        return { ok: false, notFound: true, error: `no conversation ${conversationId}`, message: null };
      }
      const isGroup = !chan || chan.type !== 'dm';

      let pks = Array.isArray(mentions) ? mentions.filter(Boolean) : null;
      if (!pks) {
        const slugOf = await this._slugSync();
        const roll = members.map((pk) => ({ id: slugOf(pk) || pk, pubkey: pk, display_name: slugOf(pk) || '', handle: slugOf(pk) ? `@${slugOf(pk)}` : '' }));
        const byId = new Map(roll.map((r) => [r.id, r.pubkey]));
        pks = present.resolveMentions(body, roll).map((r) => byId.get(r.userId)).filter(Boolean);
      }

      const att = attachment && attachment.url ? attachment : null;
      const ev = await this.client.publish({
        kind: KIND.STREAM_MESSAGE,
        content: body,
        tags: project.messageTags(conversationId, { mentions: pks, attachment: att, botId }),
      });

      // Sending clears MY unread: you have self-evidently seen a chat you just replied in.
      await this._setFrontier(conversationId, ev.created_at).catch(() => { /* badge only */ });

      return {
        ok: true,
        message: present.message({
          id: ev.id, outbound: true, text: body, at: new Date(ev.created_at * 1000),
          status: 'sent', group: isGroup, attachment: att, mentions: pks,
        }),
      };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e), message: null }));
  }

  /** Move my read frontier for one channel. 30078 is replaceable, so this REPLACES rather than
   *  appends — the whole map is rewritten each time, which is what the format requires. */
  async _setFrontier(conversationId, ts) {
    const me = this.pubkey;
    const d = project.readStateCoord(me);
    const cur = await this.client.query({ kinds: [KIND.READ_STATE], authors: [me], '#d': [d], limit: 1 });
    const contexts = project.parseReadState(cur[0]);
    contexts[conversationId] = Math.max(Number(contexts[conversationId] || 0), Number(ts || Math.floor(Date.now() / 1000)));
    await this.client.publish({
      kind: KIND.READ_STATE,
      tags: [['d', d], ['t', 'read-state']],
      content: project.buildReadState(contexts),
    });
    return contexts[conversationId];
  }

  async markRead(conversationId) {
    return this._guard(async () => {
      const last = await this.client.query({ kinds: MESSAGE_KINDS, '#h': [conversationId], limit: 1 });
      const newestEv = project.newest(last);
      await this._setFrontier(conversationId, newestEv ? newestEv.created_at : Math.floor(Date.now() / 1000));
      return { ok: true, unread: 0 };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  /** Health, for /readyz. Never throws and never hangs. */
  async probe() {
    const at = Date.now();
    const info = { engine: 'buzz', relay: this.client.wsUrl, pubkey: this.pubkey };
    try {
      const rosters = await this.client.query({ kinds: [KIND.GROUP_MEMBERS], '#p': [this.pubkey], limit: PAGE });
      const messages = await this.client.count({ kinds: MESSAGE_KINDS });
      this.lastError = null;
      return {
        ok: true, reachable: true, protocol: PROTOCOL,
        self: { id: this.selfId, pubkey: this.pubkey }, db: info,
        conversations: rosters.length, messages: messages ?? 0,
        latencyMs: Date.now() - at,
      };
    } catch (e) {
      this.lastError = { at: new Date().toISOString(), message: String((e && e.message) || e) };
      return {
        ok: false, reachable: false, protocol: PROTOCOL,
        self: { id: this.selfId, pubkey: this.pubkey }, db: info,
        error: this.lastError.message, latencyMs: Date.now() - at,
      };
    }
  }

  // ── protocol ops ──────────────────────────────────────────────────────────────────────────────
  //
  // NOTE the one that is missing: `reconnect`. Absence IS the answer — adapters/index.js derives the
  // advertised ops by asking the object which methods it has, and a local engine has no pairing to
  // redo, so a `reconnect` here could only ever say "nothing to do" and a caller could not tell that
  // apart from a re-pair that worked.

  async listGroups() {
    return this._guard(async () => {
      const all = await this.listConversations({ limit: PAGE });
      return all.filter((c) => c.group);
    }, (e) => present.degradedList(e));
  }

  async createGroup({ name, members = [], tag = 'קבוצה', pinned = false } = {}) {
    return this._guard(async () => {
      const title = String(name || '').trim();
      if (!title) return { ok: false, error: 'a group needs a name' };
      const id = crypto.randomUUID();
      await this.client.publish({
        kind: KIND.NIP29_CREATE_GROUP,
        tags: [['h', id], ['name', title], ['visibility', 'private'], ['channel_type', 'stream']],
      });
      for (const pk of await this._toPubkeys(members)) {
        await this.client.publish({ kind: KIND.NIP29_PUT_USER, tags: [['h', id], ['p', pk]] });
      }
      if (pinned) await this._pin(id, true);
      return { ok: true, id, name: title, tag };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  /** Accepts profile slugs or raw pubkeys, so callers need not know which they hold. */
  async _toPubkeys(list) {
    const out = [];
    for (const v of list || []) {
      const s = String(v || '').trim().toLowerCase();
      if (/^[0-9a-f]{64}$/.test(s)) { out.push(s); continue; }
      const p = this.profiles ? await this.profiles.get(s).catch(() => null) : null;
      if (p && p.pubkey) out.push(p.pubkey);
    }
    return [...new Set(out)];
  }

  async _pin(channelId, on) {
    const cur = await this.client.query({ kinds: [KIND.PIN_LIST], authors: [this.pubkey], limit: 1 });
    const have = new Set(project.tagValues(cur[0], 'h'));
    if (on) have.add(channelId); else have.delete(channelId);
    await this.client.publish({ kind: KIND.PIN_LIST, tags: [...have].map((h) => ['h', h]) });
  }

  /** The address book: everyone this engine knows. Profiles first — they are the identities that
   *  can act — then any other pubkey that has published a kind:0. */
  async listUsers({ q = '', limit = 200 } = {}) {
    return this._guard(async () => {
      const slugOf = await this._slugSync();
      const evs = await this.client.query({ kinds: [KIND.PROFILE], limit: Math.min(limit, PAGE) });
      const byPk = project.profilesFromEvents(evs, slugOf);
      const needle = String(q || '').trim().toLowerCase();
      return Object.values(byPk)
        .filter((u) => !needle || u.name.toLowerCase().includes(needle) || String(u.id).toLowerCase().includes(needle))
        .map((u) => ({ id: u.id, name: u.name, handle: u.handle, color: u.color, initials: present.initialsOf(u.name, u.handle) }))
        .slice(0, limit);
    }, (e) => present.degradedList(e));
  }

  /**
   * Open a 1:1. The `d` tag is DETERMINISTIC — a uuid5-style digest of the two sorted pubkeys — so
   * opening the same pair twice addresses the same channel instead of minting a second one. An
   * accidental duplicate DM is not cosmetic: half the history lands in each.
   */
  async createDirect({ userId, name = null } = {}) {
    return this._guard(async () => {
      const [pk] = await this._toPubkeys([userId]);
      if (!pk) return { ok: false, error: `no such user ${userId}` };
      // THE RELAY MINTS THE ID, not us. The `d` we send is a client-side idempotency key — a
      // deterministic digest of the two sorted pubkeys, so asking twice does not open two DMs — but
      // the channel the relay actually creates carries a uuid of its own, and that is the only id
      // anything else will answer to. Returning our `d` produced a conversation the very next
      // sendMessage could not find ("no conversation 30340b84…", measured 2026-09-02).
      const pair = [this.pubkey, pk].sort().join(':');
      const d = crypto.createHash('sha256').update(`dm:${pair}`).digest('hex').slice(0, 32);
      await this.client.publish({ kind: KIND.DM_OPEN, tags: [['p', pk], ['d', d]] });

      // Find the channel the relay bound it to: the one roster naming exactly the two of us. The
      // roster is written by the RELAY (a different author), so this cannot be filtered by author.
      const found = await this._findDirect(pk);
      if (!found) return { ok: false, error: 'the relay accepted the DM but published no channel for it' };
      return { ok: true, id: found, name: name || null };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  /**
   * The channel id of my DM with `pk`, or null.
   *
   * Retried briefly because the roster is published by the relay a moment after it accepts the
   * open — polling here is what makes createDirect a synchronous op to its caller instead of one
   * that returns an id nothing recognises yet.
   */
  async _findDirect(pk, tries = 6) {
    for (let i = 0; i < tries; i += 1) {
      const rosters = await this.client.query({ kinds: [KIND.GROUP_MEMBERS], '#p': [this.pubkey], limit: PAGE });
      for (const r of rosters) {
        const members = project.membersFromRoster(r);
        if (members.length === 2 && members.includes(pk) && members.includes(this.pubkey)) {
          return project.tagValue(r, 'd');
        }
      }
      await new Promise((res) => setTimeout(res, 400));
    }
    return null;
  }

  /** Stage an attachment. Returns the descriptor sendMessage() takes. */
  async uploadMedia({ fileName, mimeType = null, data = null, buffer = null, sourcePath = null } = {}) {
    return this._guard(async () => {
      let bytes = buffer;
      if (!bytes && data) bytes = Buffer.from(String(data), 'base64');
      if (!bytes && sourcePath) bytes = fs.readFileSync(sourcePath);
      if (!bytes) return { ok: false, error: 'uploadMedia needs data, buffer or sourcePath' };
      const name = present.safeFileName(fileName);
      const d = await this.client.uploadBlob(bytes, { mime: mimeType || 'application/octet-stream', filename: name });
      return { ok: true, id: d.sha256, name, mime: d.mime, size: d.size, url: d.url, sha256: d.sha256 };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  /**
   * Fetch an attachment's bytes as this profile.
   *
   * A PROTOCOL op, like uploadMedia: a backend that cannot serve a blob simply does not define it,
   * and the route answers 501 rather than a broken download. The relay requires Blossom auth with
   * verb `get` even for reading, which is the whole reason this cannot be a redirect.
   */
  async downloadMedia(sha) {
    return this._guard(async () => {
      const buffer = await this.client.downloadBlob(String(sha || ''));
      return { ok: true, buffer, mime: null, name: null };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  /**
   * Create a PERSON — someone to talk to. NOT an identity you can act as: that is a PROFILE, it
   * holds a credential, and engine/profiles.js makes it. Here we mint a keypair, publish its kind:0
   * so it is nameable, and DISCARD the secret — a contact that can be addressed and can never speak.
   */
  async createUser({ id = null, name, handle = null, color = null } = {}) {
    return this._guard(async () => {
      const display = String(name || '').trim();
      if (!display) return { ok: false, error: 'a user needs a name' };
      const { mintIdentity } = require('../relay/identity');
      const { nsec, pubkey } = mintIdentity();
      const tmp = new RelayClient({ nsec, wsUrl: this.client.wsUrl, httpUrl: this.client.httpUrl });
      try {
        await tmp.publish({
          kind: KIND.PROFILE,
          content: JSON.stringify({ name: display, display_name: display, ...(handle ? { nip05: handle } : {}) }),
        });
      } finally { await tmp.close(); }
      return { ok: true, id: id || pubkey, pubkey, name: display, color: color || present.colorOf(pubkey) };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  /**
   * Push. The receive path local_inbox.js dispatches bots off.
   *
   * Emits IDS, not the message, and in the SAME shape the postgres NOTIFY stream did
   * (`{kind:'message', conversation_id, message_id, sender_id, fromMe}`) — that is what let the
   * engine swap without touching local_inbox.js or a single bot. A subscriber handed a rendered
   * message would have to be trusted to merge it correctly; one handed "conversation X changed"
   * re-reads through the same getConversation every other path uses.
   */
  async subscribe(onEvent) {
    if (typeof onEvent !== 'function') throw new Error('subscribe: onEvent required');
    const me = this.pubkey;

    // MY CHANNEL SET IS NOT FIXED, so a subscription pinned to the set that existed at startup goes
    // deaf to every conversation opened afterwards — and a bot that stops answering new chats looks
    // exactly like a bot that is switched off. So the roster stream is watched too, and the message
    // subscription is re-issued whenever it changes.
    //
    // `since` is backdated a few seconds on purpose: a channel created moments before this call has
    // a roster the relay is still writing, and a message sent in the same second as `now` sat on the
    // boundary of an exclusive filter. Re-delivering a handful of seconds is harmless — local_inbox
    // dispatches by message id and the bot runtime drops anything it has already answered.
    // Everything from here is gated on the moment we started listening: a bare filter replays a
    // channel's history (see RelayClient.subscribe for why it must be bare), and a bot that wakes up
    // and answers every message it has ever received is worse than one that answers none.
    const startedAt = Date.now();
    const seen = new Set();
    const emit = (ev) => {
      if (!project.isMessage(ev) || seen.has(ev.id)) return;
      seen.add(ev.id);
      if (seen.size > 5000) seen.clear();      // bounded: this runs for the life of the process
      onEvent({
        kind: 'message',
        conversation_id: project.channelOf(ev),
        message_id: ev.id,
        sender_id: ev.pubkey,
        fromMe: ev.pubkey === me,
      });
    };

    let unMessages = null;
    let ids = [];
    const resubscribe = async () => {
      const rosters = await this.client.query({ kinds: [KIND.GROUP_MEMBERS], '#p': [me], limit: PAGE });
      const next = [...new Set(rosters.map((e) => project.tagValue(e, 'd')).filter(Boolean))].sort();
      if (next.join(',') === ids.join(',') && unMessages) return;   // nothing new to watch
      ids = next;
      if (unMessages) { await unMessages(); unMessages = null; }
      if (!ids.length) return;
      unMessages = await this.client.subscribe(
        [{ kinds: [...TIMELINE_KINDS, KIND.TYPING], '#h': ids }], emit, { sinceMs: startedAt });
    };

    // Presence is EPHEMERAL, so a bare filter replays nothing — there is no history to gate.
    const unPresence = await this.client.subscribe(
      [{ kinds: [KIND.PRESENCE, KIND.PRESENCE_SNAPSHOT] }], () => {});
    // The roster stream is NOT gated: a roster is a replaceable snapshot, so the copy the relay
    // holds may predate this process while still describing a channel we have never seen. Gating it
    // on start time would hide exactly the conversations a restarted service needs to pick up.
    const unRosters = await this.client.subscribe(
      [{ kinds: [KIND.GROUP_MEMBERS], '#p': [me] }],
      () => { resubscribe().catch((e) => console.error('[chat/buzz] resubscribe failed:', e.message)); });

    await resubscribe();
    await this.client.announcePresence('online');

    return async () => {
      await unPresence();
      await unRosters();
      if (unMessages) await unMessages();
    };
  }

  /**
   * Everything the bot runtime needs about ONE inbound message, in the normalised shape bots take.
   *
   * `members` is returned alongside because the RECIPIENT is not implied by the connection the way
   * it is on WhatsApp — one message can be inbound for several identities at once, and each may
   * have a different bot attached.
   */
  async inboundEnvelope(messageId) {
    return this._guard(async () => {
      const [ev] = await this.client.query({ ids: [messageId], limit: 1 });
      if (!ev) return { ok: false, error: 'no such message' };
      const channelId = project.channelOf(ev);
      const roster = await this.client.query({ kinds: [KIND.GROUP_MEMBERS], '#d': [channelId], limit: 1 });
      const members = project.membersFromRoster(roster[0]);
      const slugOf = await this._slugSync();
      const att = project.attachmentFromEvent(ev);
      const client = this.client;
      return {
        ok: true,
        members: members.map((pk) => slugOf(pk) || pk),
        botId: project.botIdOf(ev),
        message: {
          id: ev.id,
          conversationId: channelId,
          isGroup: members.length > 2,
          fromMe: false,     // set per RECIPIENT by the caller
          sender: { id: slugOf(ev.pubkey) || ev.pubkey, name: slugOf(ev.pubkey) || ev.pubkey.slice(0, 8) },
          text: ev.content || '',
          timestamp: new Date(ev.created_at * 1000),
          attachments: att ? [{
            id: att.sha256, kind: /^image\//.test(att.mime || '') ? 'image' : 'document',
            name: att.name, fileName: att.name, mimeType: att.mime, mime: att.mime, size: att.size,
            // THE most important function in the bot contract: the transport closes over whatever
            // it takes to produce a Buffer, and the bot just asks. Here that is an authenticated
            // Blossom GET.
            download: () => client.downloadBlob(att.url),
          }] : [],
          raw: ev,
        },
      };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  /**
   * Publish THIS profile's kind:0 — the name every other participant sees.
   *
   * Replaces the `chat_users` row the postgres engine kept: a display name is not a fact about our
   * database, it is a fact about an identity, so it lives with the identity. kind:0 is replaceable,
   * which makes this idempotent — publishing the same name twice is a no-op to every reader.
   */
  async publishSelfMeta({ name, handle = null } = {}) {
    return this._guard(async () => {
      const display = String(name || '').trim() || this.selfId;
      await this.client.publish({
        kind: KIND.PROFILE,
        content: JSON.stringify({ name: display, display_name: display, ...(handle ? { nip05: handle } : {}) }),
      });
      return { ok: true, name: display };
    }, (e) => ({ ok: false, reachable: false, error: String((e && e.message) || e) }));
  }

  async close() { await this.client.close(); }
}

module.exports = { BuzzChatBackend, PROTOCOL };
