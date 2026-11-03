# Bots — the transport-free contract

```
bots/
  chat_bot.js        the RUNTIME: discovery, attachment, dispatch
  intent.js          "does this message want an answer?" — the sim's rule, ported
  hacohen-bot/       one folder = one bot; index.js is its manifest
    index.js
    states.js  reply.js  media.js  daily_limit.js  agent_sessions.js
```

A bot is a **folder with an `index.js`**. Discovery is the filesystem — there is no registry file to
forget to update, and nothing outside a folder (this README, `intent.js`) can be loaded as a bot.

## The rule

> A bot receives a **normalised inbound message** and replies through an **injected send function**.
> It never imports a transport.

That is the whole design. A bot written once runs on local chat, WhatsApp or Telegram unchanged,
because the only thing it is allowed to know about the outside world is the two shapes below.

## The manifest

```js
module.exports = {
  id: 'hacohen-bot',              // MUST equal the folder name (see "why" below)
  name: 'בוט הכהנים',              // shown in the connection's bot picker
  desc: '…',                      // one line, shown under the name
  accepts: { groups: false, chatter: false },   // opt-in to noise; see the gate
  async onMessage(msg, ctx) { … },
};
```

**`id` must equal the folder name.** Two sources of truth for a bot's identity is how you get an
attachment record pointing at `orders-bot` while the folder is `orders`, and the failure is silent:
the connection simply stops answering. The runtime rejects the mismatch at load instead.

**`accepts` is opt-IN.** A bot that says nothing is quiet in groups and quiet on small talk. The
direction matters: a bot that forgot to implement the rule should go silent, not start answering every
line of a six-person group forever.

## The normalised inbound message (`msg`)

| field | why it exists |
|---|---|
| `id` | the transport's message id. Needed for reactions, reply-to and de-duplication. Opaque — never parsed. |
| `conversationId` | **where the message came from and where a reply goes.** The single address a bot needs, and the only argument the canonical `sendMessage` op takes. It replaces the old "reply to `senderId` in a DM but to `groupJid` in a group" split, which is precisely the branch that made a group handler a copy of the private handler. |
| `isGroup` | cannot be derived without transport knowledge (WhatsApp says `@g.us`, Telegram says a negative chat id). The transport decides once; the auto-reply gate and every "that's DM-only" product rule read it. |
| `sender.id` | a stable identity for the **person**. Subscriber state, admin checks, per-user locks and daily limits are all per-person, and in a group `conversationId ≠ person`. WhatsApp handed us two different fields for this (`remoteJid` in a DM, `key.participant` in a group); normalising both to one id is what let group and private collapse into one code path. |
| `sender.name` | display name as the transport reports it (`pushName`). Carried on the message so a greeting never needs a lookup. |
| `fromMe` | every transport echoes our own outbound messages back. Without this flag a bot answers its own reply, and since each reply quotes the last, it does so forever. The runtime drops these before any bot sees them. |
| `text` | one field. A bot must never have to know about `conversation` vs `extendedTextMessage.text` vs a caption. `null` when there is no text. |
| `timestamp` | a real `Date`. Document intake records the message date, and transports variously send seconds, milliseconds and ISO strings. |
| `attachments[]` | `{ kind, fileName, mimeType, caption, size, download() }`. **`download()` is the most important function in this contract** — Baileys needs `downloadContentFromMessage`, Telegram needs `getFile` + an HTTP GET, local chat needs a disk read. The transport closes over whichever it is; the bot just asks for a `Buffer`. This one closure is what un-welded document processing from WhatsApp. |
| `raw` | the transport payload. An escape hatch, documented as one: **reading it couples your bot to a transport.** Present because a debugging session that can't see the wire format is worse than a documented smell. |

## The context (`ctx`)

Built by the runtime from the **abstract backend** (`chatapi/adapters`), never from a socket.

| field | why it exists |
|---|---|
| `send(text)` | reply into this conversation. The floor: it is `backend.sendMessage(conversationId, {text})` and nothing else. |
| `sendLong(text)` | the same, chunked. In the runtime rather than the transport because "your reply is 40 KB" is a problem on *every* backend — WhatsApp and Telegram both cut at ~4096 and a local bubble that long is unreadable anyway. A transport may override it. |
| `sendMenu({ text, options })` | `text` is the rendered fallback every transport can use; `options` is the structured form for backends with native quick replies. Splitting them means a Telegram inline keyboard is a *transport* upgrade, not a bot rewrite. The menu **content** stays in the bot — it is that customer's menu. |
| `sendTo(otherConversationId, text)` | reply somewhere else: "that action is DM-only, come to the DM", broadcasts. Rare, but without it a bot would reach for the backend directly and start hard-coding addresses. |
| `react(emoji)` / `typing(on)` | best-effort acknowledgement. **Contractually allowed to do nothing**: WhatsApp has both, a plain local backend has neither. Making them mandatory would have blocked backends; making the bot check first would have put transport branching back inside the bot, which is the exact thing this seam removes. Use them unconditionally. |
| `can(capability)` | for the rare bot that wants to *say* something different when reactions are unavailable. |
| `intent` | the classification from `intent.js` — `kind`, `isQuestion`, `isMenuChoice`, `isChatter`, `hasLink`… Computed once by the runtime so two bots cannot disagree about what a question is. |
| `conversationId`, `connectionId`, `isGroup`, `sender` | hoisted from the message/dispatch so the common case is one hop, not two. `connectionId` in particular lets a bot keep per-connection state — the same bot on two WhatsApp numbers is two conversations, not one. |
| `backend` | the abstract backend itself, for ops a bot legitimately needs beyond sending (`markRead`, `listConversations`). Still transport-free: it is the adapter interface, not a driver. |
| `bot`, `log` | identity and a pre-namespaced logger, so every bot's output is greppable as `[bot-id@connection-id]`. |

## The auto-reply gate

Applied by the runtime **before** a bot is woken, from `intent.js`:

1. `msg.fromMe` → never.
2. no bot attached (or `none`) → never.
3. `msg.isGroup && !accepts.groups` → never. *(the sim's rule: bots do not talk in groups)*
4. empty message → never.
5. short plain chatter (≤ 24 chars, not a question / command / menu choice / link / handoff /
   attachment) `&& !accepts.chatter` → never.

`dispatch()` returns `{ handled, reason, botId }` rather than a bare boolean: "the bot said nothing"
and "the runtime never asked the bot" look identical in a chat window and completely different in a
bug report.

## Attachment

**One bot per connection.** Two bots on one conversation means two answers to one question and no
ordering rule makes that read as anything but a fault. A connection needing several behaviours is one
bot with several branches — which is exactly what `hacohen-bot` is.

```js
runtime.attach('local-chat', 'hacohen-bot');   // alias: setBot()
runtime.detach('local-chat');                  // == attach(cid, 'none')
runtime.attachedTo('local-chat');              // -> 'hacohen-bot'
runtime.listBots();                            // [{id:'none',…}, {id:'hacohen-bot',…}]
```

Defaults live in `DEFAULT_ATTACHMENTS` and are applied only to connections nobody has wired yet, so a
reload never stomps an operator's choice. `local-chat` is this stage's stated default; `wa-baileys` is
there too because hacohen-bot is **live on a real phone number**, and a default that covered only
`local-chat` would have switched the production number off silently on deploy.

## Writing a new bot

```js
// bots/echo-bot/index.js
module.exports = {
  id: 'echo-bot', name: 'Echo', desc: 'repeats questions',
  accepts: { groups: false, chatter: false },
  async onMessage(msg, ctx) {
    if (ctx.intent.isQuestion) await ctx.send(`you asked: ${msg.text}`);
  },
};
```

`mkdir` + that file is the whole registration. Nothing else in the tree changes.
