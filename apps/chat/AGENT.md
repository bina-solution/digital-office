# Operating «צ׳אט» (the `chat` app)

The office's conversations in one place: the local chat between people in the office, plus WhatsApp
(one linked phone, through Baileys) and Telegram (a bot), each an account (connection) in the
credential plane. A bot can be attached per account. Everything here reaches real people, so read
freely and send only when told to.

## From inside the office network (`http://chat:3000`, interface `chat.v1`)

**Who a call acts as:**

- With `TRUST_EDGE_AUTH=true`, the shipped default in `.env.ex`, chat trusts every in-network
  caller.
- A call with no key acts on the account it names (`connection_id` in the body or the query). With
  none, it acts on the account selected in the screen's switcher, or the first admin's.
- A profile key (`X-Chat-Profile-Key` or `Authorization: Bearer`, never in the query string) acts
  only as its own LOCAL-chat profile, never on WhatsApp or Telegram.

```bash
GET  /api/manifest · /api/accounts                 # the live contract; the accounts and their state
GET  /api/conversations?connection_id=<id>         # that account's conversations, newest first
GET  /api/conversation/<id>?connection_id=<id>     # one conversation and its messages
POST /api/conversation/<id>/send   {"connection_id": "…", "text": "…"}   # sends to the people in it
POST /api/conversation/<id>/attach (multipart file, connection_id)       # sends a file to them
POST /api/conversation/<id>/read                   # marks it read
POST /api/broadcast {"connection_id": "…", "conversation_ids": […] | "to": "all", "text": "…"}
```

The older WhatsApp-bot routes take no key and are still served, because n8n's «whatsapp api»
workflow calls them. Use the routes above for new work.

From the shell there is one verb, `./bbox chat drop-legacy-chat [--apply]`. It retires seven legacy
`chat_*` tables: without `--apply` it is a dry run, and with it the tables are dumped and dropped. It
is the owner's.

## Rules

- **Name `connection_id` on every call.** Read `GET /api/accounts` first. Without it, an op runs on
  whatever account the owner last selected, which may be his WhatsApp: a `{"to": "all"}` broadcast
  would then go to every one of its conversations.
- **These reach people, on the owner's number or bot.** Send only what the owner asked for, to whom
  he named.
  - `send`, `attach` and `/api/broadcast` (which refuses to run without `to: "all"` written out).
  - Every `/api/bot/send*`, and `/api/bot/broadcast`, which messages every subscriber, one per second.
  - `/api/bot/create-group`, which makes a WhatsApp group of the people listed.
  - `/api/bot/group-participants`, which adds, removes, promotes or demotes people.
- A bot attached to an account auto-replies to what comes in. Attaching or detaching one
  (`/api/account/bot`) changes what people receive.
- **Never without the owner's words:**
  - `DELETE /api/account/<id>` or `DELETE /connections/<id>`;
  - `DELETE /api/subscribers`, `DELETE /api/bots/<id>/settings`, or `POST /api/subscribers/restore`;
  - `POST /api/bot/disconnect`, which logs the phone out of WhatsApp;
  - `POST /api/account/select` or `/connections/select`, which move the selection every unnamed call
    falls back to.
- Phone numbers and chat histories stay inside the office. They come out of `/api/bot/state`,
  `/api/subscribers` (and its `/backup`), `/api/wa-archive/*` and `/api/export/conversations`.

## Traps

- **One phone, one socket.** A second WhatsApp socket logs the device out. Pair or re-pair only from
  the console's «חיבורים ומפתחות», never by starting another client.
- A pairing that closes with 428 and shows no QR is a browser-identifier and history-sync
  combination that `src/whatsapp/baileyes_app.js` already avoids. It is not an address block.
- A Telegram bot has no receive path here, so a bot attached to Telegram answers nobody.
- Do not move `WHATSAPP_DATA_DIR`: the session lives there, and a new path logs the phone out.
- README.md still describes the bot this app grew out of. The code above is current.

Gates: G27 (the shared screen blocks), its own tests.
