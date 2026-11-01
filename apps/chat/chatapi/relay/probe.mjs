/**
 * STAGE-0 PROBE — the eight calls that decide whether buzz can be the chat_local engine.
 *
 * This is not a test of our adapter; there is no adapter yet. It is a test of the RELAY's public
 * protocol, run exactly the way `chatapi/adapters/buzz.js` will run it: from node, over the docker
 * network, as a profile holding nothing but a Nostr keypair. Every recipe here was read off the
 * two Apache-2.0 reference clients (hardy4yooz/buzz-web `use-session-mutations.ts` +
 * `chat-model.ts`, shopstr-eng/buzz `blossom-upload.ts`) rather than invented.
 *
 * It is ALSO the upgrade gate. `ghcr.io/block/buzz` is pinned by sha in apps/chat/docker-compose.yml
 * because buzz is v0.5.x and its 127-kind registry IS its API — kinds land weekly. Bumping the pin
 * means re-running this file and getting eight PASSes; anything less means the new image changed a
 * contract chat depends on.
 *
 *   docker run --rm --network traefik-network -v "$PWD/apps/chat/chatapi/relay:/w" -w /w \
 *     node:22-slim sh -c 'npm i --silent nostr-tools >/dev/null 2>&1 && node probe.mjs'
 *
 * The eight, in the order a real conversation needs them:
 *   1 keypair            an identity is a keypair; a profile will hold one in the vault
 *   2 NIP-42 auth        the WS handshake every op rides on
 *   3 create channel     kind 9007 — `createGroup` / the DM channel behind `createDirect`
 *   4 send               kind 9 — `sendMessage`
 *   5 query              REQ/EOSE — `getConversation`
 *   6 read state         kind 30078 — `markRead`, and the `unread` count in the list
 *   7 media              kind 24242 + PUT /upload — `uploadMedia` / attachment.download()
 *   8 presence           kind 20001 — the `online` column, and the proof ephemeral kinds fan out
 */
import { finalizeEvent, generateSecretKey, getPublicKey } from 'nostr-tools/pure';
import { createHash, randomUUID } from 'node:crypto';

// node >=22 ships a global WebSocket, so the adapter needs no `ws` dependency either.
const hex = (u8) => Buffer.from(u8).toString('hex');

const RELAY_WS = process.env.PROBE_RELAY_WS || 'ws://chat-relay:3000';
const RELAY_HTTP = process.env.PROBE_RELAY_HTTP || 'http://chat-relay:3000';

const results = [];
const pass = (n, d) => { results.push([true, n, d]); console.log(`  PASS  ${n} — ${d}`); };
const fail = (n, d) => { results.push([false, n, d]); console.log(`  FAIL  ${n} — ${d}`); };

/** One authenticated socket, the shape adapters/buzz.js will hold open per profile. */
class Relay {
  constructor(sk) { this.sk = sk; this.pk = getPublicKey(sk); this.subs = new Map(); this.oks = new Map(); }

  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(RELAY_WS);
      this.ws = ws;
      const timer = setTimeout(() => reject(new Error('auth timeout')), 15000);
      ws.onerror = (e) => { clearTimeout(timer); reject(new Error('ws error: ' + (e?.message || e))); };
      ws.onmessage = (raw) => {
        let m; try { m = JSON.parse(raw.data); } catch { return; }
        const [type] = m;
        if (type === 'AUTH') {
          // NIP-42: sign the relay's challenge as kind 22242. The relay answers OK on the auth
          // event's own id, which is how we know the socket is authenticated rather than merely open.
          const ev = finalizeEvent({
            kind: 22242, created_at: Math.floor(Date.now() / 1000),
            tags: [['relay', RELAY_WS], ['challenge', m[1]]], content: '',
          }, this.sk);
          this.authId = ev.id;
          ws.send(JSON.stringify(['AUTH', ev]));
          return;
        }
        if (type === 'OK') {
          const [, id, ok, msg] = m;
          if (id === this.authId) { clearTimeout(timer); this.authed = ok; return ok ? resolve(this) : reject(new Error('auth rejected: ' + msg)); }
          const w = this.oks.get(id); if (w) { this.oks.delete(id); w({ ok, msg }); }
          return;
        }
        if (type === 'EVENT') { const s = this.subs.get(m[1]); if (s) s.events.push(m[2]); return; }
        if (type === 'EOSE') { const s = this.subs.get(m[1]); if (s) s.done(s.events); return; }
        if (type === 'CLOSED') { const s = this.subs.get(m[1]); if (s) s.done(s.events); return; }
      };
    });
  }

  publish(tmpl) {
    const ev = finalizeEvent({ created_at: Math.floor(Date.now() / 1000), tags: [], content: '', ...tmpl }, this.sk);
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('publish timeout for kind ' + tmpl.kind)), 15000);
      this.oks.set(ev.id, (r) => { clearTimeout(t); r.ok ? resolve({ ev, msg: r.msg }) : reject(new Error(`kind ${tmpl.kind} rejected: ${r.msg}`)); });
      this.ws.send(JSON.stringify(['EVENT', ev]));
    });
  }

  query(filter) {
    const sub = 'p' + Math.random().toString(36).slice(2, 10);
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('query timeout')), 15000);
      this.subs.set(sub, { events: [], done: (evs) => { clearTimeout(t); this.subs.delete(sub); this.ws.send(JSON.stringify(['CLOSE', sub])); resolve(evs); } });
      this.ws.send(JSON.stringify(['REQ', sub, filter]));
    });
  }

  /** NIP-98: a signed kind:27235 in an Authorization header. The HTTP half of the surface. */
  async nip98(method, url, extraTags = []) {
    const ev = finalizeEvent({
      kind: 27235, created_at: Math.floor(Date.now() / 1000),
      tags: [['u', url], ['method', method], ...extraTags], content: '',
    }, this.sk);
    return 'Nostr ' + Buffer.from(JSON.stringify(ev)).toString('base64');
  }

  close() { try { this.ws.close(); } catch { /* already gone */ } }
}

const main = async () => {
  console.log(`stage-0 probe -> ${RELAY_WS}\n`);
  let alice, bob, channelId, sentId;

  // 1 ── an identity is a keypair
  const skA = generateSecretKey(), skB = generateSecretKey();
  pass('1 keypair', `alice=${getPublicKey(skA).slice(0, 12)}… bob=${getPublicKey(skB).slice(0, 12)}… (nsec is ${hex(skA).length} hex chars)`);

  // 2 ── NIP-42 over the websocket
  try {
    alice = await new Relay(skA).connect();
    bob = await new Relay(skB).connect();
    pass('2 NIP-42 auth', 'two sockets authenticated as distinct pubkeys');
  } catch (e) { fail('2 NIP-42 auth', e.message); return report(); }

  // 3 ── a channel, with bob in it. This is createGroup, and the shape createDirect reuses.
  try {
    channelId = randomUUID();
    await alice.publish({ kind: 9007, tags: [['h', channelId], ['name', 'probe-room'], ['visibility', 'private'], ['channel_type', 'stream']] });
    await alice.publish({ kind: 9000, tags: [['h', channelId], ['p', bob.pk]] });   // put-user
    const roster = await alice.query({ kinds: [39002], '#d': [channelId], limit: 1 });
    const members = (roster[0]?.tags || []).filter((t) => t[0] === 'p').map((t) => t[1]);
    if (!members.includes(bob.pk)) throw new Error(`bob not in roster 39002 (${members.length} members)`);
    pass('3 create channel', `9007 + 9000 -> 39002 roster carries ${members.length} members incl. bob`);
  } catch (e) { fail('3 create channel', e.message); }

  // 4 ── send, as bob, so alice has something genuinely inbound to count as unread
  try {
    const { ev } = await bob.publish({ kind: 9, tags: [['h', channelId], ['p', alice.pk]], content: 'שלום מהבדיקה' });
    sentId = ev.id;
    pass('4 send', `kind 9 accepted, id ${ev.id.slice(0, 12)}… (Hebrew content round-trips)`);
  } catch (e) { fail('4 send', e.message); }

  // 5 ── read it back the way getConversation will
  try {
    const evs = await alice.query({ kinds: [9, 40002], '#h': [channelId], limit: 50 });
    const found = evs.find((e) => e.id === sentId);
    if (!found) throw new Error(`sent id absent from ${evs.length} events`);
    if (found.content !== 'שלום מהבדיקה') throw new Error('content mangled: ' + found.content);
    pass('5 query', `REQ/EOSE returned ${evs.length} event(s); content byte-identical`);
  } catch (e) { fail('5 query', e.message); }

  // 6 ── read state. The `unread` column and markRead both hang off this one replaceable event.
  try {
    const d = 'read-state:' + createHash('sha256').update(alice.pk).digest('hex').slice(0, 32);
    const payload = { v: 1, client_id: 'chatapi-probe', contexts: { [channelId]: Math.floor(Date.now() / 1000) } };
    await alice.publish({ kind: 30078, tags: [['d', d], ['t', 'read-state']], content: JSON.stringify(payload) });
    const back = await alice.query({ kinds: [30078], authors: [alice.pk], '#d': [d], limit: 1 });
    const parsed = JSON.parse(back[0]?.content || '{}');
    if (!parsed.contexts?.[channelId]) throw new Error('frontier absent after write-back');
    pass('6 read state', `30078 replaceable, frontier for the channel = ${parsed.contexts[channelId]}`);
  } catch (e) { fail('6 read state', e.message); }

  // 7 ── media. Blossom: sha256 of the body, a kind:24242 authorization, PUT.
  try {
    const body = Buffer.from('probe attachment — ' + new Date().toISOString(), 'utf8');
    const sha = createHash('sha256').update(body).digest('hex');
    const auth = await alice.nip98('PUT', `${RELAY_HTTP}/upload`, [
      ['t', 'upload'], ['x', sha], ['expiration', String(Math.floor(Date.now() / 1000) + 300)],
    ]);
    // The kind here is 24242, not 27235 — Blossom BUD-11 has its own auth kind.
    const ev = finalizeEvent({
      kind: 24242, created_at: Math.floor(Date.now() / 1000),
      tags: [['t', 'upload'], ['x', sha], ['expiration', String(Math.floor(Date.now() / 1000) + 300)]],
      content: 'Upload probe',
    }, skA);
    // X-SHA-256 is a MANDATORY HEADER for PUT /upload (BUD-11), not a tag on the auth event, and
    // the relay's 401 for its absence is the generic "authentication failed" — the reason only
    // appears in the relay's own log at buzz_media=debug. Cost an hour to find; the adapter must
    // always send it. (buzz-relay/src/api/media.rs:180-184)
    const hdrs = {
      Authorization: 'Nostr ' + Buffer.from(JSON.stringify(ev)).toString('base64'),
      'Content-Type': 'text/plain',
      'X-SHA-256': sha,
    };
    let res = await fetch(`${RELAY_HTTP}/upload`, { method: 'PUT', body, headers: hdrs });
    if (res.status === 404 || res.status === 405) {
      res = await fetch(`${RELAY_HTTP}/media/upload`, { method: 'PUT', body, headers: hdrs });
    }
    const text = await res.text();
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)} (nip98 hdr len ${auth.length})`);
    const descriptor = JSON.parse(text);
    // The descriptor's url is built from the tenant host; rewrite the authority to the address we
    // actually dial. GET is ALSO Blossom-authenticated (verb `get`, not `upload`) — this is the
    // exact call `attachment.download()` will make for a bot.
    const path = new URL(descriptor.url).pathname;
    const getEv = finalizeEvent({
      kind: 24242, created_at: Math.floor(Date.now() / 1000),
      tags: [['t', 'get'], ['x', sha], ['expiration', String(Math.floor(Date.now() / 1000) + 300)]],
      content: 'Download probe',
    }, skA);
    const get = await fetch(RELAY_HTTP + path, {
      headers: { Authorization: 'Nostr ' + Buffer.from(JSON.stringify(getEv)).toString('base64') },
    });
    const back = Buffer.from(await get.arrayBuffer());
    if (!get.ok) throw new Error(`GET ${path} -> HTTP ${get.status}: ${back.toString('utf8').slice(0, 160)}`);
    if (!back.equals(body)) throw new Error(`downloaded ${back.length}B != uploaded ${body.length}B`);
    pass('7 media', `${body.length}B PUT then authenticated GET ${path}, sha ${sha.slice(0, 12)}… byte-identical`);
  } catch (e) { fail('7 media', e.message); }

  // 8 ── presence. Ephemeral (20000-29999) = NOT STORED, so this proves the live-socket path the
  //      `online`/`typing` columns depend on, and is exactly why the adapter must hold a socket.
  try {
    const seen = new Promise((resolve) => {
      const sub = 'pres' + Math.random().toString(36).slice(2, 8);
      alice.subs.set(sub, { events: [], done: () => {} });
      const t = setTimeout(() => resolve(null), 8000);
      const orig = alice.subs.get(sub);
      orig.events = new Proxy([], { set(o, k, v) { if (k !== 'length' && v?.pubkey === bob.pk) { clearTimeout(t); resolve(v); } o[k] = v; return true; } });
      alice.ws.send(JSON.stringify(['REQ', sub, { kinds: [20001], limit: 0 }]));
      setTimeout(() => bob.publish({ kind: 20001, tags: [], content: JSON.stringify({ status: 'online' }) }).catch(() => {}), 400);
    });
    const got = await seen;
    if (!got) throw new Error('no 20001 fanned out to the other socket within 8s');
    pass('8 presence', `bob's ephemeral 20001 reached alice's live socket (not stored, as designed)`);
  } catch (e) { fail('8 presence', e.message); }

  alice.close(); bob.close();
  return report();
};

const report = () => {
  const ok = results.filter((r) => r[0]).length;
  console.log(`\n${ok}/${results.length} PASS`);
  process.exit(ok === results.length && results.length === 8 ? 0 : 1);
};

main().catch((e) => { console.error('probe crashed:', e); process.exit(1); });
