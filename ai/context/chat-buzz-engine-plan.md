# chat: replacing the hand-written local engine with a buzz relay

**Status:** plan + in-flight execution, opened 2026-09-02.
**Supersedes** `chat-service-plan.md` §3's build-don't-adopt verdict, and only that section — the
adapter pattern and its two rules (one choke point, cache by credential) stand unchanged.

## Why this reverses §3

`chat-service-plan.md` §3 rejected Rocket.Chat / Matrix / Mattermost because each is "a heavyweight
service with its own database, auth stack and upgrade burden … and adopting one would *still*
require an adapter, so it buys none of the abstraction work."

That reasoning holds for a *product*. `block/buzz` is evaluated here as an *engine* — the seat
docker-mailserver occupies for `mail_imap_local`. Measured, not assumed:

| | evidence |
|---|---|
| The data model covers the contract | `crates/buzz-core/src/kind.rs` — 127 kinds. Read state 30078, pin list 10001, typing 20002, presence 20001/40902, DM 41010/41001, NIP-29 groups 9007/9000/9001/39000–39003, attachments 1063 + Blossom, mentions via `p` tags |
| The schema is real relational tables | `migrations/0001_initial_schema.sql` (33 KB): `communities`, `channels`, `channel_members`, `users`, `events` (monthly partitions, `search_tsv` GENERATED + GIN, 8 indexes), `event_mentions` |
| The public protocol is sufficient | Block's own desktop client (`desktop/src-tauri/src/native_relay_client.rs`) drives everything over WS NIP-01 + NIP-42 — no privileged path |
| A JS client already exists | `hardy4yooz/buzz-web` (Apache-2.0): `relay-client.ts`, `chat-model.ts`, `use-relay-user-state.ts`, plus the shopstr fork's `blossom-upload.ts` — all on `nostr-tools` |
| It reuses what layer 1 already runs | supabase-db (a new `buzz` database) and the shared `redis` |

**What it does NOT change:** the abstract API, the UI, the bots, `local_inbox.js`, the connections
plane, the protocol id `chat_local`, or any route. Only the object `build()` returns.

## The shape

```
chat  (node — routes/UI/bots unchanged)
 ├─ chatapi/adapters/buzz.js   ← the chat_local backend (replaces local.js)
 ├─ chat_profiles (supabase-db public) + pubkey column
 └─ vault chat_local-<8hex> = { profile_id, api_key, nsec, pubkey }

chat-relay  (ghcr.io/block/buzz:sha-<7>, docker-network only, no traefik labels)
 ├─ supabase-db → database `buzz`   (one-shot init; BUZZ_AUTO_MIGRATE=true)
 ├─ redis       → the layer-1 kv service
 └─ S3          → supabase storage-api S3 protocol, else minio
```

Three findings make this small:

1. **`local_inbox.js` is already engine-agnostic** — it only calls `backend.subscribe()` and
   `backend.inboundEnvelope()` through the abstract backend. Implement those two with today's
   `{kind:'message', conversation_id, message_id, sender_id, fromMe}` shape and every bot works
   unchanged.
2. **A profile already mints a credential and a vault instance** (`engine/bootstrap.js`). A Nostr
   keypair is one more field in the same secret, under the same ledger and the same never-re-mint law.
3. **Nothing outside `apps/chat` reads `chat_*`** (verified — the only hit is a backup dump).

## Op mapping

| op | relay recipe |
|---|---|
| `listConversations` | channels `39002 #p=me` ∪ DMs `41001 #p=me`; names from `39000 #d`; `last` = one REQ carrying N filters `{kinds:[9,40002], #h, limit:1}`; `unread` = 30078 frontier vs last ts, then `POST /count` (count(all) − count(authors:[me])); `pinned` 10001; `online`/`typing` from the live socket seeded by 40902 |
| `getConversation` | `kinds:TIMELINE #h limit 500` + `39002 #d` + kind 0 batch by `authors` |
| `sendMessage` | kind 9 with `["h",ch]`, `["p",…]` mentions, `imeta` attachment, `["client","chatapi","bot:<id>"]` — the loop breaker (today's `bot_id` column) |
| `markRead` | 30078 `{v:1,client_id:"chatapi",contexts:{[ch]:ts}}`, `d=read-state:<hash>`, `t=read-state` |
| `probe` | `GET /_readiness` + one NIP-98 `POST /count` |
| `listGroups` / `createGroup` | `39000` type=group / 9007 with a client-minted uuid `h` + 9000 per member |
| `listUsers` | `13534` roster ∪ kind 0 |
| `createDirect` | 41010 with a deterministic `d` = uuid5(sorted pubkeys) → idempotent |
| `uploadMedia` | sha256 → kind 24242 auth → `PUT /media/upload` |
| `createUser` | mint keypair, publish kind 0, discard the nsec (a contact, never a speaker) |
| `subscribe` | per-profile REQ `{kinds:[9,40002,40003,5], #h:[my channels]}`, re-issued when `39002` changes |
| `inboundEnvelope` | `ids:[id]`; members `39002 #d`; `attachments[].download()` = `GET /media/<sha.ext>` with NIP-98 |
| `reconnect` | absent, as now |

Two mappings that keep bot state valid across the swap:

- **`sender.id`** = the profile slug when the pubkey belongs to a profile, else the pubkey hex. This
  is what keeps `ctx.settings.admins`, daily limits and per-user locks working.
- **`status`** = `read` when every other member's 30078 frontier ≥ the message ts, else `sent`. There
  is no `delivered` — that tick is a WhatsApp concept and is not faked.

## The ephemeral-kind consequence (the one architectural change)

Kinds 20000–29999 are **not stored**. `online` and `typing` are only true while a per-profile
WebSocket is held open. The chat service already holds a Baileys socket and a Postgres LISTEN
client, so this is the same class of thing — but it turns a stateless-per-request backend into a
stateful one. Lifecycle follows the existing fingerprint cache: `close()` on rotation.

## Stages

Each is green on its own before the next starts.

| # | stage | gate |
|---|---|---|
| 0 | **Spike.** relay + init in compose; from Node against the pinned image: mint key, NIP-42 auth, 9007 create, kind 9 send, `/query`, 30078, 24242 upload, 20001 presence | the eight calls succeed |
| 1 | relay in compose + `app.json` data/use; nothing uses it yet | `bbox run` green, `chat-relay` healthy, G30 memory-budget lint passes |
| 2 | keys — `profiles.js` + `bootstrap.js` mint nsec/pubkey into the vault; `resolveActive`'s local path goes through the vault like every remote backend | `engine_bootstrap.test.js` idempotence extended: **never re-mints an nsec** |
| 3 | `buzz.js` read side behind `CHAT_LOCAL_ENGINE=postgres\|buzz` (default `postgres`) | `local_chat_backend.test.js` shapes pass on the new projections |
| 4 | write side | `chatapi_routes.test.js` green on `buzz` |
| 5 | push + bots (`subscribe`, `inboundEnvelope`, the bot tag) | `local_inbox.test.js` green |
| 6 | flip the default to `buzz`; **cleanup** — delete `local.js`, the 7 data tables, the NOTIFY trigger; update this doc and app-engine-pattern §11 | `bbox baseline` green |
| 7 | **Telegram receive path.** Independent of buzz but required by P5: today `telegram.js` only warms a read model and **no bot ever dispatches on Telegram** (`local_inbox.js:9-17`). ~150 lines — a `getUpdates` long-poll owner with offset calling `runtime.dispatch(normalise(update), …)`, mirroring `src/whatsapp/chat_bot.js:170-183` | `telegram_backend.test.js` + a live TG reply |

## Acceptance — the owner's proof sequence

| id | proof | needs |
|---|---|---|
| **P0** | the module is `#/m/chat`, and `#/m/whatsapp` still resolves (an additive redirect — never a removed route) | — |
| **P1** | full chat UI between two local profiles at `console.localhost/#/m/chat` — send both ways, unread clears, an attachment, a group | stages 1–4 |
| **P2** | cleanup done: `local.js` and the 7 tables gone, `bbox baseline` green | stage 6 |
| **P3** | a third declared profile `hacohenbot1`, with `hacohen-bot` attached to its connection | stage 5 |
| **P4** | user1 messages hacohenbot1 → the bot answers, on the relay | stage 5 |
| **P5** | the SAME bot answers on a Telegram profile | stage 7 + an owner-supplied bot token |
| **P6** | the SAME bot answers on a Baileys profile | a QR pairing from a residential IP |

P5 and P6 need owner-supplied credentials and are the only gates this plan cannot reach on its own.

## Decisions taken with open eyes

- **S3.** supabase storage-api runs `STORAGE_BACKEND: file`; its S3-protocol server is a config-only
  enable and is unverified here — stage 0 decides. Fallback is minio, +1 container, ~128M.
- **First per-app database on supabase-db.** Precedent exists (`_supabase.sql`) and `data.sql`
  already expresses it, but it is new for a layer-3 app. The init runs as `postgres`; mind
  production's schema-ownership gotcha.
- **`BUZZ_REQUIRE_RELAY_MEMBERSHIP=false`** — correct for a docker-internal relay: every socket is
  still NIP-42 authenticated and nothing is routed. Hardening later is flipping it and adding
  `buzz-admin add-member` to bootstrap; the image ships `buzz-admin`.
- **Pin by sha.** v0.5.x, ~1,900 open PRs, kinds land weekly. Stage 0's eight calls are the upgrade gate.
