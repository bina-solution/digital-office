# Chat: from one WhatsApp bot to a chat service

## What this is

`apps/chat` is a single-platform WhatsApp bot with an admin panel. The target is a
**chat service**: a local chat backend plus multiple remote backends behind connections, several
attachable bots, and one abstract API so the UI treats every backend the same way — exactly the shape
Drive and Mail already have.

## The pattern to copy (not invent)

Mail solved this problem already; this follows it deliberately rather than designing something new.
Read `apps/mail/mailapi/adapters.py` before writing any of this — it is the reference.

| Mail | Chat |
|---|---|
| `mail_imap_local` → `LocalBackend` | `chat_local` → `LocalChatBackend` |
| `mail_imap_app_password` → `GmailBackend` | `chat_wa_baileys` → `BaileysBackend` |
| `mail_gmail_oauth` → `GmailOAuthBackend` | `chat_tg_bot` → `TelegramBackend` |
| `resolve_active(connection_id)` — the single choke point | same |
| backends cached by **credential fingerprint**, not id | same |
| synthetic local instance always present, needs no secret | same |
| `CANONICAL_OPS` derives `/manifest` from the dispatch table | same |

The two rules that make mail's version work, and that this must keep:

1. **One choke point.** Every op resolves its backend through one function, so "which account is
   this?" has exactly one answer and `/readyz` cannot disagree with the ops.
2. **Cache by credential, not by id.** A rotated token has the same connection id and a dead socket.
   Fingerprinting the secret is what makes rotation take effect without a restart.

## Stages

Each stage lands and is verifiable on its own. Do not start the next until the previous is green.

### 1 — Rename `chat` → `chat`
Directory, `app.json` id, compose service + container names, hostname, traefik hosts, blueprints,
console module alias, `scripts/lib.sh` first-party build list, `scripts/ui-coverage/*`, docs.
Keep the module display name צ׳אט (already changed). The volume `wa_media` is EXTERNAL and shared —
renaming it orphans data, so it stays.
**Verify:** `reconcile validate`, `dc config --services`, the container comes up, `/` still serves the
client. Watch for the same trap the mail rename hit: scripts that look a container up by name fail
*silently* (`seed.sh` printed "skipped" and moved on).

### 2 — The abstraction layer: `apps/chat/chatapi/`
```
chatapi/
  server.js              routes only, no backend knowledge
  adapters/index.js      CANONICAL_OPS, resolve_active(), fingerprint cache
  adapters/local.js      chat_local
  adapters/baileys.js    chat_wa_baileys   (wraps today's src/whatsapp/*)
  adapters/telegram.js   chat_tg_bot
  connections_client.js  instances + secrets from the connections service
```
Canonical ops (the contract the UI and bots both use):
`listConversations · getConversation · sendMessage · listAccounts · selectAccount · addAccount ·
reconnect · listBots · setBot · listProviders`

### 3 — The local chat backend
**Judgement, stated plainly:** mature open-source servers exist — Rocket.Chat, Matrix/Synapse,
Mattermost, Zulip. None is the right answer here. Each is a heavyweight service with its own
database, auth stack and upgrade burden, which contradicts this platform's "the OS ships a database,
not a product" stance; and adopting one would *still* require an adapter, so it buys none of the
abstraction work. A focused backend over the Postgres the platform already runs is smaller, has no
new operational surface, and is the only option that makes local chat a first-class peer of the
remote ones rather than a bolted-on server.

Scope: users, 1:1 chats, groups, membership, messages, media/file attachments, mentions, read state.

### 4 — Bots: one folder each, attached per connection
```
bots/
  chat_bot.js            the runtime: load bots, attach one per connection, dispatch inbound
  hacohen-bot/index.js   today's bot, ported and fully working
```
A bot receives normalised inbound messages from ANY backend and replies through the abstract API, so
a bot written once runs on local chat, WhatsApp or Telegram unchanged. Default: `hacohen-bot`
attached to `local-chat`.

### 5 — UI
Connection switcher like Drive/Mail, per-connection bot attachment, and the sim's chat client
(`apps/chat/.../ui/chat.ejs`, already 94/94 on component parity) driven by the abstract API.

## Known gaps in today's adapter (found before this plan)

The UI reads fields the current `chat_adapter.js` never returns, so they silently render empty:
`lastDir`, `lastStatus` (the delivery tick in the list), `online`, `typing`, and `scolor` (group
sender colour). The conversation list is also **unsorted** — the sim sorts pinned first, then by
recency. Fix these as part of stage 2 rather than patching the old adapter.
