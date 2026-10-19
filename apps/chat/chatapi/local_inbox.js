/**
 * The private engine's RECEIVE PATH — the thing that lets a bot answer on local chat.
 *
 * Baileys has one: it hands each inbound WhatsApp frame to runtime.dispatch
 * (src/whatsapp/chat_bot.js). The local engine had none, because it has no socket — so a bot could
 * be attached to a local connection, report itself attached in the UI, and never say a word. Nothing
 * errored; the bot was simply never told a message existed.
 *
 * ⚠ TELEGRAM STILL HAS NONE. This header used to claim it "does the same from its polling loop",
 * and that is not true: adapters/telegram.js `ingest()` is fed only by its own getUpdates warm-up,
 * which populates the READ model so conversations render — it never calls runtime.dispatch. Grep for
 * `.dispatch(` and there are exactly two callers, this file and the WhatsApp one. A bot attached to
 * a Telegram connection therefore reports itself attached and answers nobody, which is the same
 * silent failure this file was written to end. Left as a known gap rather than papered over: a
 * Telegram receive path needs a long-poll owner or a webhook route, and inventing one here would
 * duplicate the transport's own loop. The comment is corrected so the next reader looks.
 *
 * The relay's live subscription is that signal. ONE PER IDENTITY THAT HAS A BOT — see start() for
 * why a single shared stream cannot work here — and for each message it asks the only two
 * questions that matter: who is this inbound FOR, and does that identity have a bot?
 *
 * Two properties this file exists to get right:
 *
 *   · A message is inbound for the OTHER participants, never the sender. Dispatching to the sender
 *     is how a bot answers itself, and since each reply is itself a message it would do so forever.
 *   · Each recipient is dispatched with a backend acting AS THAT IDENTITY. A bot attached to
 *     `bot-user` must reply as bot-user, not as whoever happens to be selected in the UI — otherwise
 *     the answer arrives from the admin and the conversation makes no sense.
 */
const adapters = require('./adapters');
const bots = require('../bots/chat_bot');

let _stop = null;

/**
 * A recipient is dispatchable only if they are a PROFILE — an identity with a credential and a
 * connection. A plain contact is someone to talk to, not someone a bot can answer as, and there is
 * no connection id to attach a bot to in the first place.
 *
 * `chat_local-<userId>` used to be derivable by string concatenation. It is not any more, and that is
 * the point: an instance id is minted by the vault (`chat_local-<8hex>`) and says nothing about who
 * it is, so the mapping has to come from the profile table — the one place that holds the answer.
 */
async function instanceOf(store, profileId) {
  const p = await store.get(profileId).catch(() => null);
  return p && p.status === 'active' ? p.instance_id : null;
}

/** The identity the envelope is READ through. Any active profile would do — the envelope is the same
 *  row whoever asks — so the first admin is used and resolved once per event, not once per member. */
async function readerInstance(store) {
  const admin = await store.firstAdmin().catch(() => null);
  return admin ? admin.instance_id : null;
}

/**
 * Deliver one NOTIFY event to whichever identities have a bot attached.
 * Exported for tests: it is the whole decision, and it is worth being able to drive it directly.
 */
async function handleEvent(evt, { resolve = adapters.resolveActive, runtime = bots, store = null, readerCid = null } = {}) {
  if (!evt || evt.kind !== 'message' || !evt.message_id) return { dispatched: [] };
  const profiles = store || adapters.profiles();

  // WHO READS THE ENVELOPE MATTERS NOW, and it did not before.
  //
  // On the postgres engine the envelope was identity-neutral — the same row whoever asked — so this
  // read it through the first admin and saved a resolve. On the relay it is not: a subscription and
  // a query only ever see the channels THAT identity is in. An admin is not in a DM between two
  // other profiles, so reading through them returned "no such message" for exactly the
  // conversations a bot is most likely to be in — a private chat with the bot itself.
  //
  // So the reader is the profile the event ARRIVED for (start() passes it), falling back to the
  // first admin only for a caller that did not say.
  const cid = readerCid || (await readerInstance(profiles));
  if (!cid) return { dispatched: [], reason: 'no profile with a connection yet' };
  const { backend: reader } = await resolve(cid);
  if (typeof reader.inboundEnvelope !== 'function') return { dispatched: [] };
  const env = await reader.inboundEnvelope(evt.message_id);
  if (!env || !env.ok) return { dispatched: [], reason: (env && env.error) || 'no envelope' };

  // A BOT's output never triggers another bot.
  //
  // Without this, two identities that both have a bot attached answer each other forever: every
  // reply is a new message, which is a new inbound event, which earns another reply. It is not
  // hypothetical — the default operator inherits a bot from DEFAULT_ATTACHMENTS, so the moment a
  // second bot-bearing identity exists the pair loops. Observed live: a "hello" produced an
  // unbounded alternation of the menu and "I did not understand".
  //
  // It has to be decided from a marker on the MESSAGE, not from the sender. A rule like "never
  // dispatch when the sender has a bot attached" would also silence the admin, who has one attached
  // by default — and the admin's messages are exactly the ones that must reach a bot.
  if (env.botId) return { dispatched: [], reason: `produced by bot ${env.botId}` };

  const senderId = env.message.sender && env.message.sender.id;
  const dispatched = [];

  for (const memberId of env.members || []) {
    if (memberId === senderId) continue;                  // never answer yourself
    const cid = await instanceOf(profiles, memberId);
    if (!cid) continue;                                   // a contact, not a profile — nothing to be
    const botId = runtime.attachedTo(cid);
    if (!botId || botId === runtime.NO_BOT.id) continue;  // an identity with no bot stays silent

    let backend;
    try {
      ({ backend } = await resolve(cid));
    } catch (e) {
      // One unresolvable identity must not stop the others from being answered.
      console.error(`[local-inbox] cannot resolve ${cid}:`, e.message);
      continue;
    }

    const r = await runtime.dispatch({ ...env.message, fromMe: false }, { connectionId: cid, backend });
    dispatched.push({ connectionId: cid, botId, handled: Boolean(r && r.handled), reason: r && r.reason });
  }
  return { dispatched };
}

/**
 * Subscribe ONE STREAM PER IDENTITY THAT HAS A BOT, and keep dispatching until stop() is called.
 *
 * This used to be a single subscription on the first admin, which was right when the engine was a
 * database: LISTEN/NOTIFY is global, so one stream saw every message and the fan-out to recipients
 * happened here. A relay subscription is scoped to the identity that opened it — it delivers only
 * the channels that identity is a member of — so one admin stream is deaf to a DM between two other
 * profiles, which is precisely the conversation a bot lives in.
 *
 * One stream per bot-bearing profile is also simply the smaller idea: each stream already carries
 * only what its own bot could answer, so there is no recipient fan-out to get wrong, and a profile
 * with no bot attached costs no socket at all.
 *
 * Failure to subscribe is logged and swallowed: bot replies on the local engine are an enhancement,
 * and the alternative — refusing to start the service — would mean an engine that is briefly
 * unreachable at boot takes the whole chat app down with it.
 */
async function start({ resolve = adapters.resolveActive, runtime = bots, store = null } = {}) {
  if (_stop) return _stop;
  try {
    const profiles = store || adapters.profiles();
    const all = await profiles.list().catch(() => []);
    const stops = [];

    for (const p of all) {
      if (!p || p.status !== 'active' || !p.instance_id) continue;
      const botId = runtime.attachedTo(p.instance_id);
      if (!botId || botId === runtime.NO_BOT.id) continue;      // no bot -> no socket

      let backend;
      try { ({ backend } = await resolve(p.instance_id)); } catch (e) {
        console.error(`[local-inbox] cannot resolve ${p.id}:`, e.message);
        continue;
      }
      if (typeof backend.subscribe !== 'function') {
        console.log('[local-inbox] this backend cannot push; bots will not answer on local chat');
        return null;
      }
      const cid = p.instance_id;
      const un = await backend.subscribe((evt) => {
        handleEvent(evt, { resolve, runtime, store: profiles, readerCid: cid })
          .then((r) => {
            // A message that reaches NOBODY is the failure mode this whole path has: the bot simply
            // does not answer, and every other signal — attachment saved, connection healthy,
            // message stored — still looks right. It cost a live debugging session once
            // (inboundEnvelope was querying columns that do not exist and returning "no envelope",
            // which reads exactly like "no bot attached"). So say WHY, once, whenever a message
            // produces no dispatch at all.
            if (r && r.reason && !(r.dispatched || []).length) {
              console.warn(`[local-inbox] message ${evt && evt.message_id} dispatched to nobody: ${r.reason}`);
            }
          })
          .catch((e) => console.error('[local-inbox] dispatch failed:', e.message));
      });
      stops.push(un);
      console.log(`[local-inbox] listening as ${p.id} (${botId})`);
    }

    if (!stops.length) {
      console.log('[local-inbox] no profile has a bot attached; nothing to listen for');
      return null;
    }
    _stop = async () => { for (const un of stops) { try { await un(); } catch { /* already gone */ } } };
    return _stop;
  } catch (e) {
    console.error('[local-inbox] could not start (bots will not answer on local chat):', e.message);
    return null;
  }
}

async function stop() {
  const s = _stop;
  _stop = null;
  if (s) await s();
}

module.exports = { start, stop, handleEvent };
