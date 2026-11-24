# Operating `telegram` — «טלגרם»

The office's Telegram as the owner uses it: HIS account (a user client, not a bot), the chats the office
listens to, and every new message there as an event on the office's event stream. Agents and automations
listen to Telegram through that stream; they do not poll this app.

Vocabulary: **account** = a `telegram_user` instance in the vault (the same protocol and secret telegram-tv
uses — one login serves both). **watched chat** = a chat a person switched on; only those reach the stream.
**event** = one entry of `dgo:flow:telegram` (flow.v1): `type`, `title`, `at`, `data`.

## What you can do from here

```bash
./bbox telegram flow                 # the last 10 events, then live (== dgo telegram flow); --json for machines
./bbox telegram status               # connected? as whom? which chats? is the stream written?
./bbox telegram chats [query] [N]    # the account's chats, each with `watched`
./bbox telegram history <chat_id> [N]  # a listened-to chat's last N messages (200), oldest first; tokens masked
./bbox telegram chat "<title|id>" history all          # the whole thread — a group and the supergroup it became, merged
./bbox telegram chat <id> message <msg_id> mark 👀      # a reaction from the ACCOUNT ("" takes it off); refusals in Telegram's words
curl -s http://telegram:8984/api/flow?last=20
curl -s "http://telegram:8984/api/media?chat_id=-100…&message_id=…" -o file   # a watched message's file (≤20 MiB)
curl -s -X POST http://telegram:8984/api/send  -H 'content-type: application/json' -d '{"chat_id":-100…,"text":"…"}'
curl -s -X POST http://telegram:8984/api/watch -H 'content-type: application/json' -d '{"chat_id":-100…,"on":true}'
```

Event types: `message.new` (data: chat_id, chat, message_id, sender, sender_id, out, text, media, reply_to —
`media` is `{kind, label, name, size, mime}` or null, beside a caption, never instead of it), `message.edited`
(the same data but `reply_to`: a message whose sender changed its words; the group's desk shows the words as they are
now, DGO-1995),
`account.connected`, `account.lost`, `watch.on` (also when a watched group becomes a supergroup: data
`migrated_from`; the old id stays watched for its history), `watch.off`, `bot.token.stored`.
The owner's marks (DGO-1320): 👀 ✍ 👌 🏆 (what each means is on DGO-1320); each is a `message.mark` event.
Canonical ops (`status`, `listChats`, `watch`, `send`, `flow`, `history`, `mark`) answer `{"ok":true,"op":…,"data":…}`;
a refusal is 4xx with a Hebrew `detail` (409 = no account connected).

## The group desk (DGO-1352)

The answerer of «Bina Solutions Main» works by `relay/DESK.md` — read it before answering there. Each message of
his arrives as `TG: … msg N …` (+ `↩ msg M …` = the message he replied to) and is a request RECORD
(`relay/desk.py`, redis `dgo:desk:requests`, a `desk.request` event per change); the marks on his message follow it:

```bash
./bbox telegram say-group --for N "<answer>"     # an answer is a reply to msg N
./bbox telegram desk take N DGO-123              # ✍ worked on, under that item
./bbox telegram desk promise N "<as said>" --hours 4
./bbox telegram desk done N --proof "<what he opens or sees>"   # 👌 only when he can see it live
./bbox telegram desk close N                      # 🏆 · desk reopen N · desk drop N "<why>" · desk list
```

The relay hands the answerer «DESK SWEEP» with what is still open every 10 min when it is idle.

## Traps

- **Connecting the account is the OWNER's act, in the screen** (`/a/telegram/`): QR or phone + code. Never
  log in for him, never ask him for a code or a token in chat, never handle the session string.
- **Switching a chat on publishes its messages to every agent of the office**, including its earlier history
  through `history` (DGO-1300). A private chat is switched on only when the owner asks for it. The group in `TELEGRAM_WATCH_DEFAULT` is suggested on the first connection.
- **`/api/send` writes as the OWNER**, under his name, and only into a watched chat (403 otherwise; never BotFather). Write only what he asked to be written, in that chat.
- **A bot token goes straight from BotFather into the vault**: `POST /api/bots/token {"bot":"<username>",
  "label":"<name in the vault>"}` — BotFather's `/mybots` → the bot → «API Token» (the CURRENT token; never
  `/token`, which may mint a new one and cut off whatever uses the bot). It lands in the vault of the office
  this app runs on, as a `telegram_bot` instance; the answer says where, never the token. Another office's
  vault refuses a write over the link by design (hos-001), so a token for the MacBook's vault is fetched by
  the MacBook's own telegram app. BotFather's chat can never be watched, and a token pasted in a watched
  chat is masked before it reaches the stream.
- **The API has no login of its own** (like every platform service on the office network): only the
  office's own services reach `telegram:8984`; a person comes through the console's sign-in.
- **`/healthz` green does not mean Telegram works**; `/readyz` and `status.connected` + `status.reason` do.
- **One process per account per office**: do not enable telegram-tv with the same account on the same office.
