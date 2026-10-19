/**
 * NOSTR EVENTS → THE CLIENT'S SHAPES. Pure, and that is the point.
 *
 * The relay hands back a signed append-only event log filtered by kind. The client renders a
 * conversation list with `unread`, `pinned`, `lastStatus` and a thread of bubbles. Everything
 * between those two things is here, with no socket and no clock beyond Date.now(), so the part most
 * likely to be wrong — the field mapping — is checkable without standing anything up. That is the
 * same reasoning `tests/local_chat_backend.test.js` already applies to the postgres projection, and
 * the reason a dropped `lastStatus` is an invisible bug: the client renders a missing field as
 * EMPTY, so it shows up as a delivery tick that silently never appears.
 *
 * Every recipe below was read off the two Apache-2.0 reference clients (hardy4yooz/buzz-web's
 * `chat-model.ts` + `use-relay-user-state.ts`, shopstr-eng/buzz's `message-attachments.ts`) rather
 * than invented, and proved against the live relay by chatapi/relay/probe.mjs.
 */
const crypto = require('crypto');

const present = require('./present');
const { KIND } = require('./client');

const tag = (ev, name) => ((ev && ev.tags) || []).find((t) => t[0] === name);
const tagValue = (ev, name) => { const t = tag(ev, name); return t ? t[1] : null; };
const tagValues = (ev, name) => ((ev && ev.tags) || []).filter((t) => t[0] === name).map((t) => t[1]);

/** The channel an event belongs to. `h` is buzz's channel tag throughout (NIP-29 style). */
const channelOf = (ev) => tagValue(ev, 'h');

/**
 * The `d` coordinate of THIS profile's read-state event.
 *
 * Read state is a kind:30078 parameterized-replaceable event, so the `d` tag is its address: the
 * same `d` from the same pubkey REPLACES rather than appends, which is exactly what a moving
 * watermark wants. Derived from the pubkey so it is stable across restarts and cannot collide with
 * another profile's.
 */
function readStateCoord(pubkey) {
  return 'read-state:' + crypto.createHash('sha256').update(String(pubkey)).digest('hex').slice(0, 32);
}

/** Parse a read-state payload into `{ channelId: unixSeconds }`. Anything malformed reads as "no
 *  frontiers", never as a throw — a corrupt read marker must cost a badge, not the whole list. */
function parseReadState(ev) {
  if (!ev || !ev.content) return {};
  try {
    const v = JSON.parse(ev.content);
    if (!v || v.v !== 1 || !v.contexts || typeof v.contexts !== 'object') return {};
    const out = {};
    for (const [k, ts] of Object.entries(v.contexts)) {
      const n = Number(ts);
      if (k && Number.isFinite(n) && n > 0) out[k] = n;
    }
    return out;
  } catch { return {}; }
}

function buildReadState(contexts) {
  return JSON.stringify({ v: 1, client_id: 'chatapi', contexts });
}

/** kind:0 metadata events → `{ pubkey: {id,name,handle,color} }`. `resolve` maps a pubkey to a
 *  profile slug when it is one of ours; that is what keeps a bot's per-user state valid. */
function profilesFromEvents(events, resolve = () => null) {
  const out = {};
  for (const ev of events || []) {
    if (ev.kind !== KIND.PROFILE) continue;
    let meta = {};
    try { meta = JSON.parse(ev.content || '{}') || {}; } catch { meta = {}; }
    const slug = resolve(ev.pubkey);
    out[ev.pubkey] = {
      id: slug || ev.pubkey,
      pubkey: ev.pubkey,
      name: meta.display_name || meta.name || slug || ev.pubkey.slice(0, 8),
      handle: meta.nip05 || (slug ? `@${slug}` : ''),
      color: present.colorOf(slug || ev.pubkey),
    };
  }
  return out;
}

/** A channel's members, from its kind:39002 roster snapshot. */
const membersFromRoster = (ev) => tagValues(ev, 'p').map((p) => String(p).toLowerCase());

/**
 * kind:39000 metadata → what the list needs to name a channel.
 *
 * A DM IS A CHANNEL, and that is the single most useful thing to know about this engine. Opening
 * one (kind 41010) does not create a separate kind of object: the relay mints a channel id of its
 * OWN — not the `d` the client proposed — and publishes the same 39002 roster and 39000 metadata a
 * group gets, distinguished only by a `t=dm` tag. Verified against the live relay 2026-09-02 with
 * chatapi/relay/inspect.mjs, after an earlier reading of the NIPs led this projection to look for a
 * kind:41001 "DM created" event that the relay never emits — so every DM was invisible.
 *
 * The type therefore comes from `t`, and `channel_type` is read only as a fallback for a stream
 * channel that sets it (kind 9007 accepts it, and the relay echoes it back).
 */
function channelFromMetadata(ev) {
  if (!ev) return null;
  const id = tagValue(ev, 'd');
  if (!id) return null;
  const t = tagValue(ev, 't');
  return {
    id,
    name: tagValue(ev, 'name') || '',
    about: tagValue(ev, 'about') || '',
    type: t === 'dm' ? 'dm' : (tagValue(ev, 'channel_type') || 'stream'),
    visibility: tagValue(ev, 'visibility') || 'private',
    members: tagValues(ev, 'p'),
  };
}

/** NIP-92 `imeta` → the attachment shape the client and the bot runtime both read. */
function attachmentFromEvent(ev) {
  const t = ((ev && ev.tags) || []).find((x) => x[0] === 'imeta');
  if (!t) return null;
  const f = {};
  for (const part of t.slice(1)) {
    const i = String(part).indexOf(' ');
    if (i > 0) f[String(part).slice(0, i)] = String(part).slice(i + 1);
  }
  if (!f.url) return null;
  const size = Number(f.size);
  return {
    name: f.filename || (f.url.split('/').pop() || 'file'),
    mime: f.m || null,
    size: Number.isFinite(size) && size > 0 ? size : null,
    url: f.url,
    sha256: f.x || null,
  };
}

/** Build the `imeta` tag for an outbound attachment. */
function imetaTag(a) {
  const t = ['imeta', `url ${a.url}`, `m ${a.mime || 'application/octet-stream'}`];
  if (a.sha256) t.push(`x ${a.sha256}`);
  if (a.size) t.push(`size ${a.size}`);
  if (a.name) t.push(`filename ${a.name}`);
  return t;
}

/** The tags an outbound message carries. `botId` is the LOOP BREAKER — see below. */
function messageTags(channelId, { mentions = [], attachment = null, botId = null } = {}) {
  const tags = [['h', channelId]];
  for (const p of [...new Set(mentions)]) tags.push(['p', String(p).toLowerCase()]);
  if (attachment) tags.push(imetaTag(attachment));
  // WHY THE BOT MARKER IS ON THE MESSAGE AND NOT DERIVED FROM THE SENDER.
  // Two identities that both have a bot attached answer each other forever: every reply is a new
  // message, which is a new inbound event, which earns another reply. A rule like "never dispatch
  // when the sender has a bot attached" would also silence the ADMIN, who has one attached by
  // default — and the admin's messages are exactly the ones that must reach a bot. This is the
  // `bot_id` column the postgres engine carried, moved onto the event where it belongs.
  tags.push(botId ? ['client', 'chatapi', `bot:${botId}`] : ['client', 'chatapi']);
  return tags;
}

/** Which bot produced an event, or null. The receive path refuses to dispatch on its own output. */
function botIdOf(ev) {
  const t = tag(ev, 'client');
  if (!t) return null;
  const marker = t.slice(2).find((v) => String(v).startsWith('bot:'));
  return marker ? String(marker).slice(4) : null;
}

const isMessage = (ev) => ev && (ev.kind === KIND.STREAM_MESSAGE || ev.kind === KIND.STREAM_MESSAGE_V2);

/** Newest first, and stable: two events in the same second must not reorder between two renders. */
function newest(events) {
  const list = (events || []).filter(isMessage);
  if (!list.length) return null;
  return list.reduce((a, b) => (b.created_at > a.created_at || (b.created_at === a.created_at && b.id > a.id) ? b : a));
}

/**
 * Delivery status for an OUTBOUND message.
 *
 * `read` when every other member's read frontier has reached it, else `sent`. There is deliberately
 * no `delivered`: that middle tick is a WhatsApp concept — it means "the device acknowledged
 * receipt" — and the relay has no such signal. Inventing one from "the event was accepted" would
 * put a tick on the screen that means nothing, which is worse than the tick being absent.
 */
function deliveryStatus(createdAt, peerFrontiers) {
  const others = Object.values(peerFrontiers || {});
  if (!others.length) return 'sent';
  return others.every((ts) => Number(ts) >= Number(createdAt)) ? 'read' : 'sent';
}

/**
 * Count of messages newer than my frontier, excluding my own.
 *
 * Computed from events when we already hold them (a thread we just fetched). The list path uses the
 * relay's own /count instead — pulling every unread message of every conversation just to length an
 * array is the N+1 the postgres engine's single LATERAL query existed to avoid.
 */
function unreadFrom(events, { selfPubkey, frontier = 0 } = {}) {
  return (events || []).filter((e) => isMessage(e) && e.pubkey !== selfPubkey && e.created_at > frontier).length;
}

module.exports = {
  tag, tagValue, tagValues, channelOf,
  readStateCoord, parseReadState, buildReadState,
  profilesFromEvents, membersFromRoster, channelFromMetadata,
  attachmentFromEvent, imetaTag, messageTags, botIdOf,
  isMessage, newest, deliveryStatus, unreadFrom,
};
