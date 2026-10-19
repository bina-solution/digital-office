/**
 * A read-only window on what the relay actually stored for one identity.
 *
 * Not a test — a debugging tool, kept because the projection in adapters/buzz.js is written against
 * what the relay PRODUCES and not against what the NIPs say it should, and the two are not always
 * the same shape (a DM does not necessarily leave the same roster event a stream channel does).
 * When a conversation renders wrong, this is the fastest way to see which kind is missing.
 *
 *   docker run --rm --network traefik-network -v <repo>/apps/chat:/app -w /app \
 *     -e NSEC=<64 hex> node:22-slim node chatapi/relay/inspect.mjs
 */
import { finalizeEvent, getPublicKey } from 'nostr-tools/pure';

const WS = process.env.CHAT_RELAY_WS || 'ws://chat-relay:3000';
const sk = Buffer.from(process.env.NSEC, 'hex');
const me = getPublicKey(sk);

const ws = new WebSocket(WS);
const oks = new Map(); const subs = new Map();
let authId = null;

const ready = new Promise((resolve) => {
  ws.onmessage = (raw) => {
    const m = JSON.parse(raw.data);
    if (m[0] === 'AUTH' && typeof m[1] === 'string') {
      const ev = finalizeEvent({ kind: 22242, created_at: Math.floor(Date.now() / 1000), tags: [['relay', WS], ['challenge', m[1]]], content: '' }, sk);
      authId = ev.id; ws.send(JSON.stringify(['AUTH', ev])); return;
    }
    if (m[0] === 'OK') { if (m[1] === authId) return resolve(); const w = oks.get(m[1]); if (w) w(m); return; }
    if (m[0] === 'EVENT') { const s = subs.get(m[1]); if (s) s.buf.push(m[2]); return; }
    if (m[0] === 'EOSE' || m[0] === 'CLOSED') { const s = subs.get(m[1]); if (s) s.done(); }
  };
});
await ready;

const q = (filter) => new Promise((resolve) => {
  const id = 'i' + Math.random().toString(36).slice(2, 8);
  const s = { buf: [], done: () => { subs.delete(id); ws.send(JSON.stringify(['CLOSE', id])); resolve(s.buf); } };
  subs.set(id, s);
  ws.send(JSON.stringify(['REQ', id, filter]));
  setTimeout(s.done, 6000);
});

const show = (label, evs) => {
  console.log(`\n${label} — ${evs.length}`);
  for (const e of evs.slice(0, 8)) {
    const tags = e.tags.map((t) => `${t[0]}=${String(t[1] || '').slice(0, 40)}`).join(' ');
    console.log(`  kind ${String(e.kind).padEnd(6)} ${e.id.slice(0, 10)} by ${e.pubkey.slice(0, 8)} | ${tags} | ${String(e.content).slice(0, 50)}`);
  }
};

console.log('me =', me);
show('39002 rosters naming me', await q({ kinds: [39002], '#p': [me], limit: 50 }));
show('41001 DMs naming me', await q({ kinds: [41001], '#p': [me], limit: 50 }));
show('41010 DM opens I authored', await q({ kinds: [41010], authors: [me], limit: 50 }));
show('39000 channel metadata', await q({ kinds: [39000], limit: 50 }));
show('9 / 40002 messages', await q({ kinds: [9, 40002], limit: 20 }));
show('0 profiles', await q({ kinds: [0], limit: 20 }));
ws.close();
