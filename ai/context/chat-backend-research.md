# Chat backend — adopt a chat server, or finish the one we started?

Research and decision, 2026-07-29. Every licence, version and npm date below was fetched from the
primary source on that date. Where a claim could not be verified from a primary source it says
**unverified** rather than asserting.

**Verdict, stated plainly: BUILD. Finish `apps/chat/chatapi`. Do not adopt a chat server.**
The runner-up, if that is overridden, is **Mattermost** — and only Mattermost. Everything else is
eliminated on licence, RAM, datastore, or shape, and the reasons are recorded below so this does not
get re-litigated from memory.

---

## What is actually being decided

The platform has an abstract chat port — nine duck-typed methods in
`apps/chat/chatapi/adapters/index.js` — with **three backends already written against it**:
`LocalChatBackend` (Postgres, 691 lines), `BaileysBackend` (WhatsApp, 601 lines), `TelegramBackend`
(Bot API, 561 lines). The question is whether backend #1 gets finished, or gets replaced by a
third-party server.

That framing matters, because it is the thing most "which chat server should I use?" comparisons get
wrong here: **this platform's chat is a multi-protocol aggregator, not a team-chat app.** One Hebrew
RTL UI renders local chat, WhatsApp and Telegram through one pair of wire shapes. Every candidate
below is a single-protocol team-chat server. Adopting one makes it *protocol #4* — it does not
replace the engine, and it does not serve WhatsApp or Telegram at all.

### The port any candidate must satisfy

From `apps/chat/chatapi/adapters/index.js` — 5 mandatory ops, 4 optional, capability derived by
asking the object which methods it has:

```
listConversations({limit})            getConversation(id,{limit})     sendMessage(convId,{text,mentions,attachment})
markRead(convId)                      probe()                          — mandatory
reconnect()  listGroups({limit})  createGroup({name,members,...})  uploadMedia({fileName,mimeType,...})  — optional
```

Wire shapes (also contract — a missing field renders as EMPTY, not as an error):

```
conversation { id, name, handle, initials, color, tag, group, unread, pinned, online, typing,
               lastDir, lastStatus, last, mins }
message      { id, dir, text, mins, status, sender?, scolor? }
```

### What exists today

Seven tables in `apps/chat/chatapi/db/schema.sql`, on the shared `supabase-db` Postgres:
`chat_users`, `chat_conversations`, `chat_members`, `chat_messages`, `chat_attachments`,
`chat_mentions`, `chat_reads`. Five indexes. No migration runner — the file is `CREATE … IF NOT
EXISTS` executed by `ensureSchema()` on first DB op.

**Realtime does not exist.** `apps/chat/src/api/ui/chat.ejs:771` polls every 8 s
(`var POLL_MS=8000`). No WebSocket, no SSE, no `LISTEN/NOTIFY` anywhere in `apps/chat`.

---

## The constraint that decides this

`ai/context/low-memory-mode.md:4` — *"This host gives Docker only ~8 GB total"*, and the documented
triage under pressure **explicitly includes stopping the `chat` container** as non-essential.
`ai/context/api-abstraction-refactor.md:150` — *"Compose limits are TOO HIGH for 8GB"*; raising to
12 GB is marked *"Not safe to raise on 8GB unattended (OOM risk)"*.

The generated stack (`.generated/compose.yml`) includes 19 app composes = **40 services**, whose
declared `deploy.resources.limits` sum to **~26 GB on an ~8 GB host**. The box is already
overcommitted by ~3× and the docs treat that as a live production problem, not a theoretical one.

Against that, here is what each candidate's **own documentation** demands, before any of our traffic:

| Candidate | Containers | Vendor-documented floor | Fits? |
|---|---|---|---|
| **Mattermost** | 2 → **1** reusing our Postgres | **1 vCPU / 2 GB** (1–1,000 users) | Tight but yes |
| **Zulip** | **5** (zulip, db, memcached, rabbitmq, redis) | 2 GB; **4 GB + 2 CPU at 100+ users**; needs swap under 5 GB | Marginal |
| **Synapse** | 1–2 + workers | *"At least 1 GB of free RAM"* to join large public rooms | Yes, but see licence |
| **Tuwunel** (Matrix, Rust) | 1 | not stated — **unverified** | Probably, but RocksDB |
| **Chatwoot** | **4** (rails, sidekiq, pgvector, redis) | **4 GB RAM, 4 cores** | No |
| **Rocket.Chat** | 2 | **4 GiB app + 4 GiB MongoDB = 8 GiB, 4 vCPU** | **No — that is the whole VPS** |
| **Novu** | **7** | 4 vCPU / 8 GB + Mongo 2 GB + Redis 2 GB ≈ **12 GB** | No |
| **CometChat** on-prem | **~15+** (TiDB + Kafka + Mongo + 2× Redis + observability) | not published — **unverified**, empirically 16–32 GB | No |

Sources: [Mattermost hardware requirements](https://docs.mattermost.com/deployment-guide/software-hardware-requirements.html) ·
[Zulip requirements](https://zulip.readthedocs.io/en/latest/production/requirements.html) ·
[Synapse installation](https://element-hq.github.io/synapse/latest/setup/installation.html) ·
[Chatwoot requirements](https://developers.chatwoot.com/self-hosted/deployment/requirements) ·
[Rocket.Chat system requirements](https://docs.rocket.chat/v1/docs/system-requirements) ·
[Novu self-hosting](https://docs.novu.co/community/self-hosting-novu/overview) ·
[CometChat on-prem](https://www.cometchat.com/docs/on-premise-deployment/docker/overview)

**Rocket.Chat, Chatwoot, Novu and CometChat are eliminated here and do not need a feature debate.**

---

## Licence gate

This was the stated gating factor, so it is resolved first and from the actual `LICENSE` files, not
from memory. Two of the three things the brief was worried about turned out to be **wrong in our
favour**, and one turned out worse than expected.

| Project | Exact licence (verified 2026-07-29) | Does it force us open-source? |
|---|---|---|
| **Mattermost** | **Three at once.** Compiled binaries produced by Mattermost, Inc. → **MIT**. Source you compile yourself → **AGPL v3.0** or commercial. `server/templates/`, `server/i18n/`, `server/public/`, `webapp/` → **Apache 2.0**. `server/enterprise/` → Mattermost Source Available License. [LICENSE.txt](https://github.com/mattermost/mattermost/blob/master/LICENSE.txt) | **No.** Running the official image = consuming a *compiled version produced by Mattermost, Inc.* = MIT. AGPL §13 never engages. Last LICENSE.txt edit was 2024-10-01, a monorepo path refresh — **no recent relicense**. |
| **Synapse** | **Dual: AGPLv3 OR paid Element Commercial License.** Verbatim from [README](https://github.com/element-hq/synapse): *"dual-licensed by Element Creations Ltd … either (1) for free under the terms of the GNU Affero General Public License … OR (2) under the terms of a paid-for Element Commercial License agreement."* | Not automatically — a separate process spoken to over HTTP is not a derivative work. But Element **sells a commercial licence precisely to remove that doubt**, which tells you the ambiguity is real and priced. Any patch we make to Synapse itself becomes AGPL and §13-triggering. |
| **Dendrite** | AGPL-3.0 or Element Commercial | Same as Synapse — but see status below, it is moot. |
| **Tuwunel** | **Apache-2.0** ([repo](https://github.com/matrix-construct/tuwunel)) | No. Cleanest Matrix licence. |
| **conduwuit** | Apache-2.0 — **but archived** | N/A |
| **Zulip** | **Plain Apache 2.0, no carve-outs** ([LICENSE](https://raw.githubusercontent.com/zulip/zulip/main/LICENSE)) | **No. Cleanest licence in the whole field.** |
| **Rocket.Chat** | MIT outside `ee/` and `apps/meteor/ee/` ([LICENSE](https://raw.githubusercontent.com/RocketChat/Rocket.Chat/develop/LICENSE)) | No — but the *product* has hard caps, see below. |
| **Chatwoot** | **MIT since 2019, never relicensed.** `enterprise/` carved out 2021-12-09 (commit *"chore: Introduce enterprise edition license (#3209)"*). FAQ is explicit: *"This also allows you to build and resell derivatives of Chatwoot Community edition."* [FAQ](https://developers.chatwoot.com/self-hosted/faq) | No. The feared relicense **did not happen**. |
| **Novu** | Open-core: `LICENSE-MIT` + **`LICENSE-ENTERPRISE`** (Novu Proprietary). GitHub now classifies the repo as `"Other"`. EE terms prohibit *"commercial hosting services"* and require prior written approval. | The EE half would. Moot — it is not a chat engine. |
| **mautrix-whatsapp / -telegram** | **AGPL-3.0** ([LICENSE](https://raw.githubusercontent.com/mautrix/whatsapp/main/LICENSE)) | Not for unmodified use as a separate process; yes for any patch. |
| **Tinode** | GPLv3 + commercial option — **unverified**, not independently confirmed | Would need confirming before adoption. |

### The licence finding that actually bites

It is not a licence at all — it is **Rocket.Chat's product gating**, which is worse than a licence
problem because it is a runtime cap. [docs.rocket.chat/docs/our-plans](https://docs.rocket.chat/docs/our-plans)
and the [Starter page](https://www.rocket.chat/get-started) state Community Edition is capped at
**100 concurrent users**, push notifications capped at **10,000/month**, *"limited to core messaging
(basic channels and direct messages)"*, and — in their own words — *"Not suitable for production
deployment by organizations that depend on Rocket.Chat for business-critical operations."* The free
Starter plan is **$0 up to 50 users**.

Worse, enforcement arrived mid-version: [issue #31149](https://github.com/RocketChat/Rocket.Chat/issues/31149)
documents users hitting a surprise 25-user cap after upgrading to v6.5.0 **with no changelog entry**.
The Pro plan was retired 2026-04-29 and [rocket.chat/pricing](https://www.rocket.chat/pricing) is now
Commercial/Government/Defense with "contact sales" and no public price.

**A vendor that has already tightened the free tier once, silently, mid-version, is the single
highest relicensing/regating risk in this field.** Rocket.Chat is out twice over.

---

## Candidates eliminated, with the reason

| Candidate | Eliminated because |
|---|---|
| **Rocket.Chat** | 8 GiB documented floor (= the whole VPS) · MongoDB 8.x with a **mandatory replica set** (`?replicaSet=rs0` hardcoded in the official compose), i.e. a second DB engine · CE capped at 100 concurrent users, silently enforced · `@rocket.chat/sdk` last published **2019-02-07 — seven years abandoned** (npm, verified) |
| **Chatwoot** | **Wrong shape, decisively.** `conversations` has `validates :contact_id, presence: true` — one conversation = exactly one contact. `conversation_participants.user_id` is *agents only*, guarded by `ensure_inbox_access`; it is a watcher list, not membership. There is **no group, room, membership or reaction model**. It is `1 contact ↔ N agents` by design. Also 4 GB / 4-core floor. Genuinely excellent otherwise — MIT, 115-op API, signed webhooks, monthly releases — and a strong candidate *if the platform ever wants a support desk*. It is not a chat engine. |
| **Dendrite** | **Maintenance mode.** README, verbatim: *"It is currently in maintenance mode, meaning only security fixes are being applied."* Still beta: *"not feature-complete"*, *"not ready for massive homeserver deployments"*. **6 commits in 2026**; last release v0.15.2, **2025-08-15**. |
| **conduwuit** | **Archived by the owner on 2026-05-29, read-only** (code stopped 2025-04-09). README: *"Tuwunel is the ONLY official successor to conduwuit, no other project or fork is."* |
| **Conduit / Tuwunel / Continuwuity** | **Correcting the brief's premise: the whole family is Apache-2.0, not AGPL.** Tuwunel (**v1.8.2, 2026-07-17**) and Continuwuity (**v26.7.1, 2026-07-27**, 8.2% of the federation) are both alive and very active. But **all of them are RocksDB-only — there is no PostgreSQL support anywhere in the family**, verified against Continuwuity's config reference, which has no `database_backend` option at all. On a box where Postgres is layer 1 and already running, adding an opaque embedded store is a pure cost. Neither publishes RAM figures. |
| **Novu** | Not a chat engine. No rooms, no user→user messages, no history between users, no reactions. Model is Workflows/Subscribers/Topics — a Topic is a broadcast fan-out list. ~12 GB self-hosted, and it brings **MongoDB**. **Good complement** for the notification bell; never a replacement. *(The feared MIT relicense did not happen — the core is still MIT, with a separate proprietary `enterprise/`.)* |
| **Centrifugo** | **Correctly flagged in the brief: a realtime transport, not a chat engine.** Apache-2.0 (relicensed **MIT → Apache-2.0 at v3, 2021-08-31**), **25.9 MB image**, single node needs no Redis, and an *experimental Postgres broker*. It gives WS/SSE/WebTransport fan-out, channel presence, JWT auth and history-with-recovery. It gives you *zero* of: users, rooms, membership, persistence, media, receipts, search, moderation. Its docs are blunt that history *"is deliberately not a durable message queue… your application database stays the source of truth."* See "what we are not adopting" below. |
| **Nakama** | Apache-2.0 **clean, no added restrictions** (verified by diff), one Go binary, **uses our existing Postgres**, and `senderId` is a literal parameter on `ChannelMessageSend` — the cleanest licence + footprint + impersonation combination in the field. Rejected anyway: **no attachment pipeline and no threads**, a **4096-byte message cap** (Hebrew UTF-8 is ~2 bytes/char), game-domain vocabulary (matches/leaderboards/parties), and `@heroiclabs/nakama-js` last published **2024-06-21**. It gives less than Mattermost with more impedance, and media is the owner's stated worry. |
| **Let's Chat** | **Dead, confirmed.** Last commit **2019-10-03**; **archived by the owner 2025-12-01**. |
| **Tinode** | **GPL-3.0 on the server** — and, contrary to the brief's assumption, **no documented commercial/dual-licence path could be found**. Also: no full-text search, no reactions, ~1000 connections/node without fd tuning, and **bus factor 1** (all recent commits from one maintainer). Real project, wrong risk profile. |
| **Stream / Sendbird / Twilio Conversations / CometChat cloud / Ably / PubNub** | **SaaS. Not self-hostable.** Disqualified on the hard constraint that this platform runs on its own VPS. Detail retained below because the brief asked for it. |

---

## The Matrix question, answered separately

Matrix deserves its own paragraph because it is the option people assume is right.

**Technically it is the most complete protocol in this document.** Power levels, threads, reactions,
redactions with tombstones, typing, receipts, `/sync` with pagination, multi-device, E2EE, server-side
thumbnailing, an Application Service API for bots, and the **mautrix bridges** — which are the most
mature WhatsApp/Telegram bridges that exist anywhere.

Two things about it are genuinely attractive and should be said before the rejection. **The
Application Service API is an excellent fit for this shape of integration** — namespace reservation,
push-based `PUT /_matrix/app/v1/transactions/{txnId}`, user masquerading via `?user_id=`, and
**rate-limit exemption**. Our platform is structurally a bridge, and that is exactly what the AS API
is for. And **`POST /_synapse/admin/v1/users/{id}/login` mints an access token for any user**, so our
own auth stays the source of truth and no Matrix passwords are ever handled.

**And it is still the wrong choice here.**

1. **Hebrew search is hardcoded to English.** Synapse's full-text search hardcodes
   `to_tsvector('english', …)` and the config manual exposes only `enable_search` on/off — **no
   language or dictionary option**. The spec also states search *"will not include rooms that are end
   to end encrypted."* For a Hebrew platform this makes Synapse's search unusable as shipped, so we
   would build our own index anyway — which is most of the argument for adopting it gone.
2. **No per-recipient delivery receipts.** Confirmed from the
   [receipts module spec](https://spec.matrix.org/latest/client-server-api/#receipts): only `m.read`
   and `m.read.private`, both whole-timeline **watermarks**. The only proposal, MSC4089, is an open
   draft labelled `needs-implementation` with unresolved scaling objections. **Matrix cannot answer
   "did user X receive message Y."** The brief asks for exactly that.
3. **Reactions are not server-aggregated.** Spec verbatim: *"`m.annotation` relationships are NOT
   aggregated by the server"* — unlike threads and edits, counts are absent from `m.relations`, so we
   tally and dedupe them ourselves. Also no forwarding primitive, no audit log, and tombstones do
   **not** transfer membership.
4. **Operational friction on this box specifically.** `rc_message` defaults to **0.2/s, burst 10**
   (~12 msg/min) — survivable only via appservice rate-limit exemption. Synapse's Postgres database
   must be created `--encoding=UTF8 --locale=C`; it **refuses to start** on the wrong collation, so it
   cannot simply share our existing database. Releases are **biweekly with forward-only schema
   migrations and narrow rollback windows** (v1.157.2 shipped 2026-07-28 with 6 high-severity fixes).
   And Synapse's own docs call presence *"the main reason people have a poor matrix experience on
   resource constrained homeservers"* — on our box it would have to be off.
5. **The bridges do not conflict with Baileys — but they replace it.** *(Correcting an earlier draft
   of this document: there is no protocol collision.)* `mautrix-whatsapp` uses
   [whatsmeow](https://github.com/tulir/whatsmeow) and pairs as a **separate** linked device with its
   own Noise/Signal keys, so it will not stream-replace `baileys@7.0.0-rc.9`. The real objections are
   different and worse: **temp-ban codes aggregate at the account level across all devices**, so a
   ban kills Baileys *and* the bridge together — and mautrix's own docs warn that ban risk rises when
   *"initiating DMs to non-contacts"*, which is what an outbound business platform does. Add the
   linked-device slot budget (phone + 4 devices, per WhatsApp's
   [2023 announcement](https://blog.whatsapp.com/one-whatsapp-account-now-across-multiple-phones);
   the current figure is **unverified**), pure duplication of a working integration, and **+3
   containers with 3 separate databases** (mautrix docs: *"Shared postgres instance is fine, but
   shared database is not"*). **mautrix-whatsapp is a replacement for Baileys, not an addition.**
6. **E2EE is a liability here, not a feature.** Matrix v1.18 made cross-signing effectively
   mandatory — a bot that merely uploads device keys gets keys withheld and its messages hidden.
   Worse for us: `matrix-js-sdk`'s crypto store is **indexeddb-or-in-memory only**, so in Node the
   crypto state is lost on every restart ([open issue #4769](https://github.com/matrix-org/matrix-js-sdk/issues/4769)).
   The only working Node path is `matrix-bot-sdk` + `@matrix-org/matrix-sdk-crypto-nodejs` — and that
   SDK shipped **7 commits in 2026 under a single maintainer**.

**Licence-change history, which the brief asked for explicitly.** Element announced the Apache-2.0 →
AGPLv3 move on [2023-11-06](https://element.io/blog/element-to-adopt-agplv3/); v1.98.0 (2023-12-12)
was the last Apache release; **v1.99.0 on 2024-01-16 was the first AGPL release**, whose notes say it
came *"with CLA to enable Element to sell AGPL exceptions."* Dendrite and the Element clients followed
in Sept 2024 — **client SDKs were explicitly carved out and remain Apache-2.0**, which is why
`matrix-js-sdk` is still under `matrix-org`, not `element-hq`. The community verdict is visible in the
star counts: `matrix-org/synapse` retains **12,104** stars against `element-hq/synapse`'s **4,463**.

**And the governance risk is real.** The [FY2025 Foundation annual report](https://matrix.org/blog/2026/03/annual-report/)
says verbatim that it remains *"disproportionately dependent on Element's in-kind donations and
financial support, which is unsustainable"*, with Automattic's membership alone ≈50% of revenue; the
Finance Committee reports it *"still can't afford the bare minimum requirements."* Meanwhile Element's
**Synapse Pro** is a proprietary Rust reimplementation of Synapse's workers. The 2023 relicensing and
Synapse Pro are two halves of one commercial strategy — precisely the pattern the brief flags as a
real risk.

For the record, SDK health is good where it is not crypto: `matrix-js-sdk` **42.1.0-rc.0, 2026-07-28,
Apache-2.0** (npm, fetched directly); `matrix-bot-sdk` **0.8.0, 2026-01-16, MIT** — and note Element
maintains a more recently pushed fork at `element-hq/matrix-bot-sdk`. If federation with outside
organisations ever becomes a product requirement, this section gets reopened and Matrix wins.

---

## Feature matrix — what the two real contenders actually give

Only Mattermost and Zulip survive licence + RAM + datastore. "Build" is the current engine plus the
work costed in the next section.

| Feature | Build (today → after work) | Mattermost | Zulip |
|---|---|---|---|
| Multi-participant group chat | groups + membership **exist** | Yes — but **group DMs cap at 8** (`ChannelGroupMaxUsers = 8`, [channel.go](https://raw.githubusercontent.com/mattermost/mattermost/master/server/public/model/channel.go)); use private channels above that. Default team cap **50 users**, config-raisable | Yes, streams/channels, no small cap |
| Roles / moderation | `chat_members.role` column exists (`owner\|admin\|member`), **unenforced** | Yes; granular RBAC is **paid** | Yes |
| Threads / replies | absent | Yes | Yes (topics — its core model) |
| Reactions | absent | Yes | Yes |
| Edit / delete + tombstones | `deleted_at` column exists, **never written**; no edit path | Yes | Yes |
| Typing indicators | hardcoded `typing: false` | Yes | Yes |
| Presence | `online_at` column exists, **never written** | Yes | Yes |
| Per-recipient read receipts | `chat_reads` = **watermark per (conv,user)** | **No per-message receipts.** Channel-level `last_viewed_at` only — you derive per-message by comparing `create_at ≤ last_viewed_at` | **Yes, true per-user**: `GET /api/v1/messages/{id}/read_receipts` → `user_ids: [...]`, Zulip 6.0+ ([docs](https://zulip.com/api/get-read-receipts)) |
| Delivery receipts (distinct from read) | `status` enum has `delivered`, **never set** | No | No |
| Full-text search | client-side filter only; no server search | Postgres; **Elasticsearch is paid**, core search capped at 3M posts | Postgres |
| History pagination | **absent** — limits are unreachable hardcoded defaults | Yes | Yes |
| Multi-device | N/A (see single-identity gap) | Yes | Yes |
| Push notifications | absent (`platform-base/notifications` exists, unwired) | Yes | Yes (own service needed self-hosted) |
| E2EE | absent | **None** | **None** |
| Voice notes | absent | Yes | Via attachment |
| Video | absent | Yes | Via attachment |
| Images + thumbnails | absent (`sharp@0.33.5` already a dependency) | Yes | Yes |
| Arbitrary files + size limit | `uploadMedia` op exists; `multer` present | **100 MB** default, configurable | **`MAX_FILE_UPLOAD_SIZE = 100` MB** |
| Stickers / location / contacts | absent (Telegram adapter parses inbound only) | Partial | Partial |
| Forwarding | absent | Yes | Yes |
| Pinning | `pinned` column exists + indexed, **no op sets it** | Yes | Yes |
| Mentions | **done** — `chat_mentions` table + op | Yes | Yes |
| Retention policy | absent | **Paid** | Yes |
| Rate limiting | generic HTTP only (`express-rate-limit` on `/api/`), not chat-aware | Yes | Yes |
| Webhooks / bots | bot runtime exists (`apps/chat/bots/chat_bot.js`) | Yes | Yes |
| Audit log | absent | **Paid** (advanced audit) | Partial |

Mattermost paid-only, from [pricing](https://mattermost.com/pricing/): data retention policies,
compliance export, legal hold, advanced audit logging, Elasticsearch, custom user groups, read-only
channels, guest accounts, shared channels, granular RBAC.

---

## Headless API quality — the decisive axis

| | Mattermost | Zulip | (for reference) Chatwoot |
|---|---|---|---|
| REST completeness | API v4, complete | Excellent, famously well documented | 115-op Application API, OpenAPI 3.1 in-repo |
| Realtime | WebSocket API | **Long-poll `register`/`events` queue — not WebSocket** | ActionCable WS, self-described *"experimental… backward compatibility cannot be guaranteed"* |
| Node SDK freshness *(npm, fetched 2026-07-29)* | **`@mattermost/client` 11.8.0, 2026-06-22, MIT** | **`zulip-js` 2.1.0, 2024-10-22 — ~21 months stale** | none official; `chatwoot-sdk` ~9 downloads/week |
| **Post as arbitrary end users** | **Solved and documented.** `POST /api/v4/users/{user_id}/tokens` — *"Must have `create_user_access_token` permission. For non-self requests, must also have the `edit_other_users` permission."* ([users.yaml](https://raw.githubusercontent.com/mattermost/mattermost/master/api/v4/source/users.yaml)). Mint a PAT per end user, hold them, act as each natively. | Possible but **off the documented path**. Public [bots API](https://zulip.com/api/interactive-bots-api) explicitly says you **cannot** *"send messages on behalf of or impersonate other users."* Source shows `POST /api/v1/messages` accepts `forged`/`sender`/`time` gated on `can_forge_sender`, both marked `DOCUMENTATION_PENDING`. Grantable via `manage.py change_user_role can_forge_sender`. Bonus: lets you **backfill original timestamps**. | Platform API creates accounts/users |
| UI coupling | none — server is a Go binary | none | none |

This row is the strongest single argument for Mattermost and against Zulip: our platform must post as
many different end users, and Mattermost supports that with a documented, permissioned API while
Zulip supports it through an undocumented flag with no stability guarantee.

---

## Bridges to WhatsApp and Telegram

**Nothing here beats what we already have, and one thing actively threatens it.**

| Option | Status |
|---|---|
| `baileys@^7.0.0-rc.9` (ours, live) | Owns the only socket, in `apps/chat/src/whatsapp/baileyes_app.js`. Session on disk at `apps/chat/data/auth_info/` via `useMultiFileAuthState`. History in a **separate SQLite archive** (`apps/chat/src/data/wa_archive.js`) projected into the wire shapes at read time. **Working. Do not touch.** |
| `TelegramBackend` (ours) | Already implemented — 561 lines, protocol `chat_tg_bot`, Bot API over `fetch`, 509 lines of tests. **Not "planned" — built.** Its store is in-memory only, and attachment send returns `unsupported`. |
| **mautrix-whatsapp** | Genuinely the healthiest bridge ecosystem that exists — **v26.07, 2026-07-16**, monthly releases on the 16th, never missed, effectively corporate-funded (Tulir Asokan works on Beeper at Automattic). **AGPL-3.0 with no commercial escape** — the `LICENSE.exceptions` carve-outs name Beeper and Element only. **A replacement for Baileys, not an addition** — see the Matrix section. |
| **mautrix-telegram** | Also v26.07; **fully rewritten in Go on bridgev2, shipped 2026-04-16** — it is no longer a Python project. Mature, and buys us little: we already have a Telegram adapter. |
| **matterbridge** | The generic multi-protocol option. **Dormant** — last release v1.26.0 on **2023-01-29**, last push 2024-12-12, 339 open issues. Do not build on it. |
| **slidge** (+ slidge-whatsapp, slidgram) | The real XMPP bridge answer in 2026, not Spectrum 2. AGPL-3.0, actively developed (commits 2026-07-28/29), self-described "beta-grade". Also whatsmeow-based. Moot unless XMPP is adopted. |
| **Spectrum 2 / biboumi / whatsxmpp / transWhat** | **All dead or irrelevant.** Spectrum 2 has *no WhatsApp backend at all* and its last release was 2023-06-12; biboumi is IRC-only by design; whatsxmpp's last commit was 2021-06-01; transWhat/yowsup predate WhatsApp multi-device and **cannot connect**. |
| **Evolution API** | Apache-2.0, ~9.1k stars, active, wraps Baileys, ships a native Chatwoot integration. Relevant only if Chatwoot were adopted — which it is not. |

Two things worth acting on regardless of this decision, both verified from npm/GitHub on 2026-07-29:

- **Our Baileys pin is healthy.** [WhiskeySockets/Baileys](https://github.com/WhiskeySockets/Baileys)
  is **MIT**, ~10.3k stars, last commit **2026-07-29**, npm `latest` = `7.0.0-rc14`. We are on
  `^7.0.0-rc.9`. MIT is friendlier than whatsmeow's MPL-2.0 for a commercial self-hosted product, so
  there is no reason to switch engines.
- **Check what the Telegram adapter is built on.** `grammY` is healthy (v1.45.1, last commit
  2026-07-17, ~1.26M weekly downloads). **Telegraf has been stalled since 2025-01-10**, and
  **GramJS was archived by its owner on 2026-07-14** (successor: `teleproto`). `TelegramBackend`
  currently calls the Bot API over raw `fetch`, which sidesteps all of this — but if a library is
  ever added, make it grammY.

The correct pattern under any option is the one we already use: **our Baileys service stays the
transport and feeds the chat engine.** No bridge, no second WhatsApp session.

---

## XMPP — and the number that settles it

ejabberd, Openfire and Prosody are mature, small, cheaply licensed and battle-tested. Licences are
**better** than the Matrix side: **ejabberd GPL-2.0** with an OpenSSL exception (no network-use
trigger), **Openfire Apache-2.0**, **Prosody MIT**. Footprints are excellent — the `ejabberd/ecs`
image is **39 MB**, Prosody runs in ~25 MB. And XMPP is genuinely *strong* exactly where this brief
is anxious: per-recipient delivery receipts (XEP-0184) and read markers (XEP-0333) are first-class
protocol features, which is more than Mattermost offers.

They still lose, and now there is a number for it. **Of the 26 features in the brief, 11 are 100%
client work on XMPP — the server only routes them**: threads/replies, reactions, typing, read
markers, OMEMO, stickers, location, forwarding, **pinning** (no XEP exists at all), mentions, and
thumbnails on every server but ejabberd. Eight features the server genuinely does (group chat, roles,
presence, pagination, multi-device, upload limits, roster, retention); three are config; four are
split.

**We are the client.** So adopting XMPP means adopting a protocol *and still* writing the reaction
aggregation model, the `<replace>` correction folding (no server does this anywhere), the XEP-0085
typing state machine, per-participant read aggregation ("seen by 12 of 30" **is not a primitive in
XMPP**), sticker packs, and the entirety of pinning.

Two traps worth recording even though we are not adopting:

- **The archiving trap.** Bodiless stanzas carry every modern feature. ejabberd's `should_archive/2`
  requires a non-empty `<body>` or `<subject>` unless the stanza carries an explicit
  `<store xmlns='urn:xmpp:hints'/>` — so **reactions, markers, retractions and edits silently vanish
  from history** without that hint.
- **Prosody's `archive_expires_after` defaults to `"1w"`** on both `mod_mam` and `mod_muc_mam`. It
  will quietly eat your history.

Per-server: **ejabberd is the best of the three** — 200+ REST commands, `send_message` takes an
explicit **`from`** argument, it is the only server that applies retraction/moderation (XEP-0424/0425)
to the archive, and — **correcting an earlier assumption in this document** — it *does* do
server-side thumbnailing via `mod_http_upload`'s `thumbnail` option (default `false`, backed by
[eimp](https://github.com/processone/eimp)). **Openfire is disqualified outright**: its REST plugin's
`/messages/users` endpoint is broadcast-only and **cannot send as a user**, and the `Openfire-Chat`
plugin that solved this was archived 2020-03-10. Prosody's `mod_rest` is the only true bidirectional
option but is **Stage-Alpha**, and `mod_admin_rest` has been dead since 2017.

Node client health (npm, fetched 2026-07-29): `@xmpp/client` **0.14.0, 2025-10-29, ISC** — still
sub-1.0 after ~10 years; `stanza` **12.22.1, 2026-03-28, MIT**; `strophe.js` **5.0.0, 2026-07-21** is
the healthiest of the three.

**The tell:** the honest architecture for XMPP here is *"XMPP as transport + presence + fan-out, with
a parallel Postgres projection that folds the stanza stream into your real domain model — threads,
reactions, read state, pins, and a Hebrew-tokenised FTS index. Do not try to make MAM your
database."* That parallel Postgres projection **is the build option**. XMPP would add a protocol,
a container and a stanza-plumbing burden on top of work we would do anyway.

MongooseIM (GPL-2.0, **6.7.0, 2026-05-13**, Erlang Solutions, GraphQL + REST admin API) is the
best-maintained alternative to ejabberd if this ever reopens.

---

## The SaaS options, for completeness

All are **commercial SaaS, not self-hostable**, and therefore disqualified by the platform's
self-hosted constraint. Recorded so the question is closed.

| Vendor | Self-host? | ~10k MAU | Note |
|---|---|---|---|
| **Stream** | No | **$399–599/mo** | Best technical product in the field. `stream-chat` **9.50.2, 2026-07-16, 462k downloads/wk** — isomorphic, best-in-class. EU (Dublin) region. Revisit only if self-hosting stops being a requirement. |
| **Sendbird** | No | contact sales — **unverified** | Client SDK excellent (200k/wk); the **server** SDK has **198 downloads/wk** and its predecessor has rotted since 2022-11-14 without a deprecation flag. Use the Platform API with `fetch`, or don't. |
| **Twilio Conversations** | No | ~$477/mo | **Highest platform risk, and functionally inadequate.** No native reactions, no native threads, **no presence at all**. Now titled **"Conversations (classic)"** with docs moved to `/docs/conversations-classic/` and the old namespace reassigned to an AI-agent product. Twilio already sunset Programmable Chat in 2022 and killed Programmable Chat in Flex on 2026-06-01. |
| **CometChat** | Enterprise on-prem only | ~$1,249/mo+ | ~15+ containers on-prem. Infeasible. |
| **Ably Chat** | No | tiered | Persistence 30 d default. **Typing indicators bill per keystroke per subscriber per heartbeat** — the pricing model penalises exactly the group-chat pattern wanted. No threads, no media. |
| **PubNub** | No | $550/mo | Most predictable pricing (MAU-inclusive). `@pubnub/chat` alive. |

---

## Project health, in one table

Release dates and commit counts as of 2026-07-29. npm dates were fetched from `registry.npmjs.org`
directly; GitHub figures come from the research passes (direct API access was rate-limited).

| Project | Latest release | Date | Licence | Control | Licence-change history |
|---|---|---|---|---|---|
| **Mattermost** | v11.9.0 | 2026-07-08 | MIT (their binaries) / AGPL (source) / Apache-2.0 (parts) | Mattermost, Inc. | **None recent** — last LICENSE.txt edit 2024-10-01 was a path refresh |
| **Zulip** | 12.1 | 2026-06-26 | **Apache-2.0, no carve-outs** | Kandra Labs | **None. Cleanest in the field.** |
| **Synapse** | v1.157.2 | 2026-07-28 | AGPLv3 **or** Element Commercial | Element, CLA required | **Apache-2.0 → AGPLv3, first AGPL release 2024-01-16** |
| **Chatwoot** | v4.16.2 | 2026-07-27 | MIT + proprietary `enterprise/` | Chatwoot Inc. | MIT 2019; `enterprise/` carve-out 2021-12-09; **no relicense since** |
| **Rocket.Chat** | 8.6.1 | 2026-07-10 | MIT + proprietary `ee/` | Rocket.Chat Technologies | Code unchanged, but **free tier capped mid-version without a changelog entry**; Pro plan retired 2026-04-29 |
| **ejabberd** | 26.04 | 2026-04-20 | GPL-2.0 + OpenSSL exception | ProcessOne | None |
| **Openfire** | 5.1.1 | 2026-07-07 | Apache-2.0 | Ignite Realtime (community) | None |
| **Prosody** | 13.0.6 | 2026-05-27 | MIT | Independent | GPL-2.0 → MIT, at its third release |
| **Centrifugo** | v6.9.1 | 2026-07-13 | Apache-2.0 (+ commercial PRO) | Centrifugal Labs | **MIT → Apache-2.0 at v3, 2021-08-31** |
| **Nakama** | v3.40.0 | 2026-07-13 | Apache-2.0, unmodified | Heroic Labs | None |
| **Tinode** | v0.25.3 | 2026-07-04 | GPL-3.0 server | One maintainer | None; **no commercial path found** |
| **Continuwuity** | v26.7.1 | 2026-07-27 | Apache-2.0 | Community (~8) | None |
| **Tuwunel** | v1.8.2 | 2026-07-17 | Apache-2.0 | Sponsor-funded | None |
| **Dendrite** | v0.15.2 | **2025-08-15** | AGPLv3 or Commercial | Element | Apache-2.0 → AGPL, Sept 2024 |
| **conduwuit** | — | **archived 2026-05-29** | Apache-2.0 | dead | — |
| **Let's Chat** | — | **archived 2025-12-01** | MIT | dead | — |
| **mautrix-\*** | v26.07 | 2026-07-16 | AGPL-3.0, no commercial escape | ~1 maintainer (~90%) | None |

**The licence-change pattern the brief asked about is real and it is Element's**: relicence to AGPL
(2023), then sell a proprietary product against it (Synapse Pro, 2024). Rocket.Chat's version of the
same instinct is a silent runtime cap. Zulip, Openfire, Nakama and Centrifugo have clean histories.

---

## Build vs adopt — the honest arithmetic

This is the part that should not be soft-pedalled. **Building is a lot of work.** Here is the
feature-by-feature estimate for one developer on the existing Node 22 / JS / Postgres engine,
including tests to the standard already set in `apps/chat/tests/`.

| # | Missing feature | Dev-weeks | Note |
|---|---|---|---|
| 1 | **Realtime transport (WebSocket)** | **2.0** | The foundation. Replaces the 8 s poll. Nothing below it (typing, presence, live receipts) is possible first. In-process `ws` — no new container. |
| 2 | **Multi-user sessions / identity** | **2.0** | The most dangerous existing gap. `CHAT_SELF_USER` is process-wide today — *every operator shares one identity*. Needs per-user auth via Authentik. |
| 3 | Roles / permissions / moderation | 1.0 | Column exists, enforcement does not. |
| 4 | Threads / replies | 1.0 | `parent_id` + query + UI. |
| 5 | Full-text search | 1.0 | Hebrew is the hard part — see risk 3. |
| 6 | Push notifications | 1.0 | Wire the existing `platform-base/notifications` service. |
| 7 | Voice notes | 1.0 | Record UI + opus storage + playback. |
| 8 | Video | 1.0 | Upload + poster frame. **Transcoding excluded** (+2.0 if ever required). |
| 9 | Webhooks / bots API | 1.0 | Bot runtime already exists. |
| 10 | Edit/delete + tombstones | 0.75 | `deleted_at` exists; needs a write path + edit history. |
| 11 | Per-message read/delivery receipts | 0.75 | Derive from the existing watermark — cheap and correct for this UX. |
| 12 | History pagination | 0.75 | Keyset cursor on `(created_at, id)` — **the index already exists**. |
| 13 | Retention / deletion policy | 0.75 | Purge job + config. |
| 14 | Group membership ops (add/remove/leave/delete) | 0.75 | Entirely missing today. |
| 15 | Audit log | 0.75 | |
| 16 | Presence | 0.5 | Column exists; needs a heartbeat writer. |
| 17 | Reactions | 0.5 | |
| 18 | Images + thumbnails | 0.5 | `sharp` already a dependency. |
| 19 | Arbitrary file types + limits | 0.5 | `multer` + `uploadMedia` already present. |
| 20 | Stickers | 0.5 | |
| 21 | Location | 0.5 | |
| 22 | Forwarding | 0.5 | |
| 23 | Chat-aware rate limiting | 0.5 | |
| 24 | `createUser` / `createDirect` ops | 0.5 | Missing from the port entirely. |
| 25 | Typing indicators | 0.25 | Trivial once #1 exists. |
| 26 | Pinning | 0.25 | Column + index exist; no op sets it. |
| 27 | Contacts (vCard) | 0.25 | |
| — | Mentions | **0 — done** | `chat_mentions` + op shipped. |
| — | **E2EE** | **excluded** | 4+ weeks, and it *breaks* server-side search, bots and WhatsApp handling. **Do not build it.** |
| | **Total** | **≈ 21 dev-weeks** | + ~30% for review/QA/integration → **≈ 27 dev-weeks** |

**≈ 6 months for one developer, ≈ 3 months for two.** That is the real number and it should not be
rounded down.

### So why is building still right?

Because the comparison is not 27 weeks versus zero.

- Adopting **does not remove the UI work**. `ai/context/chat-port-plan.md` measured the sim-vs-live
  gap on 2026-07-29 as *"sim 94 | live 117 | present 10 (11%) | absent 84"*. Eighty-four absent
  components get built either way.
- Adopting **does not remove the adapter work** — Mattermost's model still has to be flattened into
  the nine ops and the `mins`/`dir`/`status` shapes.
- Adopting **does nothing for WhatsApp or Telegram**, which are two of the three protocols behind the
  port.
- Adopting **adds** a second identity system to reconcile with Authentik, a second source of truth, a
  monthly upgrade treadmill, and ~2 GB on a box whose own runbook says to *stop the chat container*
  when memory is tight.

Realistically, adopting Mattermost saves perhaps **12–14** of the 21 feature-weeks and costs **6–8**
integration weeks plus permanent operational overhead. The net saving is roughly a month — bought
with a permanent 2 GB and a permanent dependency, on the one resource the platform provably does not
have.

**That trade is not worth it. Build.**

### What we are *not* adopting, and the one thing we might

Do **not** add Centrifugo now. For a single `chat` container with this user count, in-process `ws`
gives the same result with zero containers, and zero containers is the whole point.

Centrifugo is nonetheless the right escape hatch to write down: Apache-2.0, a **25.9 MB** image, no
Redis needed for a single node, and an *experimental PostgreSQL broker* if it ever needs more. It
becomes correct **only** if `chat` has to run more than one replica — at which point in-process
fan-out breaks and Centrifugo is close to a drop-in. Its own docs are honest about the boundary:
channel history *"is deliberately not a durable message queue… your application database stays the
source of truth"* — which is fine, because our application database is the source of truth by design.
Deferred decision, not a current one.

---

## The staged plan

Do not attempt 27 weeks as one project. Ship in the order that retires risk.

**Stage 1 — the foundation (4 weeks).** Realtime WebSocket (#1) and multi-user identity (#2). These
two unblock everything and fix the worst existing defect: one shared identity for all operators.
Nothing else should start first.

**Stage 2 — the multi-participant correctness the owner is worried about (4 weeks).** Roles
enforcement (#3), group membership ops (#14), `createUser`/`createDirect` (#24), threads (#4),
reactions (#17), edit/delete (#10), typing (#25), presence (#16), pinning (#26).

**Stage 3 — media, the other stated worry (3.5 weeks).** Files + limits (#19), images + thumbnails
(#18), voice notes (#7), video without transcoding (#8), stickers (#20), location (#21),
contacts (#27).

**Stage 4 — scale and safety (5.5 weeks).** Pagination (#12), search (#5), push (#6), retention (#13),
rate limiting (#23), audit log (#15), receipts (#11), forwarding (#22), webhooks/bots (#9).

Stages 2 and 3 are exactly the two things the brief says the owner is worried about, and together
they are **7.5 developer-weeks** — not six months. The six-month figure is the full "everything
Telegram does" scope, and most of it is Stage 4.

---

## If this is overridden: the concrete Mattermost shape

Recorded so the fallback is executable, not hypothetical.

- **Containers added: one.** `mattermost/mattermost-team-edition` (not enterprise-edition — the
  official compose ships enterprise, which runs free-tier but carries Source Available terms on
  `server/enterprise/`). Point `MM_SQLSETTINGS_DATASOURCE` at the existing `supabase-db` alias with
  its own database. **No new Postgres.** Budget 2 GB in `deploy.resources.limits` and expect to take
  it from n8n's 3 GB.
- **A fourth adapter**, `apps/chat/chatapi/adapters/mattermost.js`, protocol `chat_mattermost`, plus
  one `if` in `build()` in `adapters/index.js`. That is the entire wiring surface — the port was
  designed for this.
- **What the adapter calls:** `GET /api/v4/users/{id}/channels` → `listConversations`;
  `GET /api/v4/channels/{id}/posts` → `getConversation`; `POST /api/v4/posts` → `sendMessage`;
  `POST /api/v4/channels/members/{user_id}/view` → `markRead`; `GET /api/v4/system/ping` → `probe`;
  `POST /api/v4/channels` → `createGroup`; `POST /api/v4/files` → `uploadMedia`. Realtime via the
  WebSocket API, replacing the 8 s poll for this protocol only.
- **Identity:** an admin token with `edit_other_users` mints a PAT per end user via
  `POST /api/v4/users/{user_id}/tokens`; store them beside the other secrets in the `connections`
  service, not on disk.
- **Migration from the seven tables:** create a Mattermost user per `chat_users` row, a private
  channel per `chat_conversations` row (**not** a group DM — the 8-member cap), members from
  `chat_members`, then replay `chat_messages` oldest-first. **Mattermost has no timestamp-forging
  API**, so replayed history collapses to import time — original `created_at` is lost. `chat_reads`
  maps cleanly onto `last_viewed_at`. `chat_attachments` must be re-uploaded through
  `POST /api/v4/files`. Keep the seven tables read-only as the archive; do not dual-write.
- **What is lost or made harder:** original message timestamps on import · group DMs above 8 members ·
  per-message read receipts (channel watermark only — though that is *what we have today*, so no
  regression) · retention, audit and Elasticsearch move behind a paid tier · Hebrew search quality is
  unchanged, because it is a Postgres problem, not a Mattermost one · and WhatsApp/Telegram stay
  exactly where they are, on the other two adapters, unaffected and unhelped.

---

## Top three risks of recommending "build"

**1. The estimate is a floor, and the scope as stated is unbounded.**
"Everything every standard chat does (Telegram, Discord, WhatsApp)" is not a specification — those
products have hundreds of engineer-years each. 27 dev-weeks buys the listed features at the quality
bar of `apps/chat/tests/`, not Telegram's polish. The mitigation is the staged plan: Stages 2 and 3
are 7.5 weeks and cover both stated worries. If Stage 4 is treated as mandatory before launch, this
recommendation gets much weaker and Mattermost gets much stronger.

**2. We now own the security surface a mature server would have given us for free.**
Today *every operator shares one identity* (`CHAT_SELF_USER` is process-wide — the comment in
`apps/chat/docker-compose.yml` admits it). Multi-user sessions, per-conversation authorisation, chat
rate limiting, retention and moderation all become ours to get right. A homegrown session or
authorisation bug in a business chat is a real incident, and Mattermost's has been attacked for a
decade and ours has not. This is why identity is Stage 1 and not Stage 4.

**3. Hebrew full-text search will be mediocre, and no option on this box fixes it.**
PostgreSQL ships **no Hebrew stemmer** — [Snowball](https://snowballstem.org/algorithms/) publishes
Arabic but **not Hebrew** (verified 2026-07-29). The realistic build is the `simple` configuration
plus `pg_trgm` trigram matching, which is language-agnostic but returns substring-quality results, not
stemmed ones.

**This risk is identical under build and under adopt — and under two candidates it is strictly
worse.** Synapse hardcodes `to_tsvector('english', …)` and exposes only `enable_search` on/off, with
no language option at all; Mattermost's core search is Postgres with Elasticsearch behind a **paid**
tier. The only good answer anywhere is a Hebrew analyser (HebMorph) on Elasticsearch/OpenSearch, and
this VPS cannot host one. Building at least means we choose the tokenisation ourselves instead of
inheriting someone's hardcoded English. It is listed here because it will be blamed on the build if
it is not written down first.

---

## What could not be verified

- **WhatsApp's current linked-device cap.** Meta's help page is fully JS-rendered; the "phone + 4
  devices" figure rests on WhatsApp's [2023 announcement](https://blog.whatsapp.com/one-whatsapp-account-now-across-multiple-phones).
  The shared-ban-fate argument against mautrix does not depend on it.
- **RAM figures for the Rust homeservers (Tuwunel, Continuwuity), the mautrix bridges, ejabberd,
  Nakama and Tinode.** None of these projects publishes any. Every number circulating for them is
  third-party folklore, so none is quoted here as fact.
- **Whether ejabberd's XEP-0431 search works on PostgreSQL** — the 25.07 docs say it *"only works if
  mod_mam is using the MySQL storage backend."*
- **Openfire's MUC `max_users` default, file-upload defaults, and rate-limiting equivalent.**
- **Whether Synapse does video thumbnailing** — the image formats (jpeg/png/webp/gif) were read from
  `synapse/media/thumbnailer.py`; the absence of video handling is inferred from source, not
  documented.
- **Whether a formal EOL exists for Twilio Conversations.** The `"(classic)"` rename and the
  namespace reassignment are verified; the inference that an EOL follows is not.
- **Sendbird pricing above 5k MAU and CometChat's on-prem RAM floor** — neither vendor publishes them.
- **Any Element/New Vector layoffs**, and whether the Matrix.org Foundation has hired a permanent
  Managing Director since Robin Riley stepped down 2025-10-28. Absence of evidence, not evidence of
  absence.
- **GitHub star and commit-cadence figures** were rate-limited on direct API access and come from the
  research passes rather than a live read. The **npm dates and licences are first-hand**, fetched
  from `registry.npmjs.org` on 2026-07-29, as are every `LICENSE` file and vendor requirements page
  quoted above.
- The session's 200-call web-search budget was exhausted partway through; remaining gaps are where a
  claim could not be closed by direct fetch of an official doc, spec, changelog or source file.

---

## Rule for this decision

The port in `apps/chat/chatapi/adapters/index.js` is the asset, not any particular backend. It has
three implementations already and adding a fourth is one `if`. **Finish `LocalChatBackend` against
that port; do not replace the port.** Revisit only on two triggers: the VPS reaching 16 GB (Mattermost
becomes genuinely attractive), or federation with outside organisations becoming a product
requirement (Matrix becomes the only answer).
