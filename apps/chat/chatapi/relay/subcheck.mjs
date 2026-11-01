/**
 * Does a live REQ actually deliver a roster the relay writes AFTER the subscription opened?
 *
 * The receive path depends on it twice over: once to notice a new conversation at all (the roster
 * stream), and once to carry the message (the per-channel stream). A one-shot query proves neither.
 *
 *   docker run --rm --network traefik-network -v <repo>/apps/chat:/app -w /app \
 *     -e NSEC=<bot nsec> -e PEER=<other pubkey> node:22-slim node chatapi/relay/subcheck.mjs
 */
import { finalizeEvent, getPublicKey } from 'nostr-tools/pure';
import { randomUUID } from 'node:crypto';

const WS = process.env.CHAT_RELAY_WS || 'ws://chat-relay:3000';
const sk = Buffer.from(process.env.NSEC, 'hex');
const me = getPublicKey(sk);
const peer = process.env.PEER;

const ws = new WebSocket(WS);
const oks = new Map(); const subs = new Map();
let authId = null;
const seen = [];

await new Promise((resolve) => {
  ws.onmessage = (raw) => {
    const m = JSON.parse(raw.data);
    if (m[0] === 'AUTH' && typeof m[1] === 'string') {
      const ev = finalizeEvent({ kind: 22242, created_at: Math.floor(Date.now() / 1000), tags: [['relay', WS], ['challenge', m[1]]], content: '' }, sk);
      authId = ev.id; ws.send(JSON.stringify(['AUTH', ev])); return;
    }
    if (m[0] === 'OK') { if (m[1] === authId) return resolve(); const w = oks.get(m[1]); if (w) w(m); return; }
    if (m[0] === 'EVENT') { seen.push([m[1], m[2]]); const s = subs.get(m[1]); if (s) s.buf.push(m[2]); return; }
    if (m[0] === 'EOSE') { const s = subs.get(m[1]); if (s && s.eose) s.eose(); }
  };
});
console.log('authed as', me.slice(0, 12));

const now = Math.floor(Date.now() / 1000);
// three shapes of the same question, to see which the relay honours on a LIVE subscription
const filters = {
  'rosters #p + since': { kinds: [39002], '#p': [me], since: now - 10 },
  'rosters #p no since': { kinds: [39002], '#p': [me] },
  'messages any, since': { kinds: [9, 40002], since: now - 10 },
  'rosters #p limit0': { kinds: [39002], '#p': [me], limit: 0 },
  'messages any limit0': { kinds: [9, 40002], limit: 0 },
};
for (const [label, f] of Object.entries(filters)) {
  const id = label.replace(/\W/g, '').slice(0, 12);
  subs.set(id, { buf: [] });
  ws.send(JSON.stringify(['REQ', id, f]));
  console.log('REQ', id, JSON.stringify(f));
}

await new Promise((r) => setTimeout(r, 1500));
console.log('\n--- publishing a DM open + a message ---');
const pub = (tmpl) => new Promise((resolve, reject) => {
  const ev = finalizeEvent({ created_at: Math.floor(Date.now() / 1000), tags: [], content: '', ...tmpl }, sk);
  oks.set(ev.id, (m) => (m[2] ? resolve(ev) : reject(new Error(m[3]))));
  ws.send(JSON.stringify(['EVENT', ev]));
  setTimeout(() => reject(new Error('timeout kind ' + tmpl.kind)), 10000);
});

await pub({ kind: 41010, tags: [['p', peer], ['d', randomUUID().replace(/-/g, '')]] });
console.log('dm opened; waiting 4s for the roster to land on the live subs…');
await new Promise((r) => setTimeout(r, 4000));

for (const [id, s] of subs) console.log(`  sub ${id}: ${s.buf.length} event(s)`, s.buf.map((e) => e.kind).join(','));

// now send into whatever channel the roster named
const roster = [...subs.values()].flatMap((s) => s.buf).find((e) => e.kind === 39002);
if (roster) {
  const ch = roster.tags.find((t) => t[0] === 'd')[1];
  console.log('\nsending into', ch);
  await pub({ kind: 9, tags: [['h', ch]], content: 'subcheck ping' });
  await new Promise((r) => setTimeout(r, 3000));
  for (const [id, s] of subs) console.log(`  sub ${id}: ${s.buf.length} event(s)`, s.buf.map((e) => e.kind).join(','));
} else {
  console.log('\nNO 39002 arrived on any live subscription — that is the defect.');
}
ws.close();
