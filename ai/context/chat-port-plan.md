# Chat (chat) — porting the sim's client onto the WhatsApp app

## Where it stands

Measured 2026-07-29 by comparing component classes in `digital-office/sim/chat.html` against
`apps/chat/src/api/ui/*.ejs`:

```
chat   sim 94 | live 117 | present 10 (11%) | absent 84
```

Chat is the **only remaining app with a real porting gap**. The others resolved as:

| app | sim source | result |
|---|---|---|
| my-docs, notifications, machine, any-concurrency, connections | the sim bundles the **real** file | identical by construction |
| drive | sim-local copy | **183/183 (100%)** — nothing to port |
| mail | sim-local copy | 126/128 — the 2 absent (`grp`, `sub`) are `syncNav` classes deliberately removed |
| indox | sim-local copy | sync surface ported; repos→instances still open (product decision) |
| **chat** | sim-local copy | **84 components absent** — this document |

The two UIs are not versions of one another. The sim's is a **chat client**: conversation list,
thread column, composer, presence, typing, tags, day separators, bot controls. Live's is a
**subscriber admin panel**. Nothing was lost — the client was simply never built.

## The gap is presentation, not data

The live app already holds everything the client needs; it exposes it in a different shape.

| Chat UI calls | Live already serves | Mapping |
|---|---|---|
| `GET /api/conversations` | `GET /api/wa-archive/chats` | rename + shape rows |
| `GET /api/conversation/:id` | `GET /api/wa-archive/messages/search` | filter by chat id |
| `GET /api/accounts` | `GET /api/bot/state` | one WhatsApp account today; the array is what makes it multi-provider later |
| `GET /api/bots` | `GET /api/bot/state` | bot roster + enabled flag |
| `POST /api/account/reconnect` | `GET /api/bot/qr`, `POST /api/bot/disconnect` | re-pair flow |
| send a message | `POST /api/bot/send` | already correct |

So the work is an **adapter**, not a new backend. That matters for sequencing: the adapter can land
and be tested on its own, before any UI changes.

## Order of work

1. **Adapter endpoints** in `src/api/api.js`, expressed purely in terms of the existing archive/bot
   calls. No new storage, no schema change. Each returns the shape the sim client already consumes,
   so the client needs no edits to talk to it.
2. **Serve the client.** The sim page is self-contained HTML with the platform's own design tokens
   (same `--accent`, same `--font` — it already satisfies the theme-token gate G21). It becomes the
   app's main UI; the existing admin page stays reachable, because subscriber management, backup and
   restore have no equivalent in the client and deleting them would remove working function.
3. **Charset fix (B5).** Hebrew arrives mojibake'd in places; fix at the boundary that reads it, not
   by patching strings downstream.
4. **Multi-provider (B3).** `/accounts` returning an array is the whole hinge: today it holds one
   WhatsApp entry, and a second provider becomes a second element rather than a second UI.

## Rule for this port

The same one the mail port earned: **do not copy sim scaffolding into production.** The sim's
`overlay/mail.js` compose window (`mlc-*`) was correctly NOT ported, because the live app had a
better implementation through the shared modal. Check each chat component the same way — port what
the app genuinely lacks, not what the sim happened to need to fake a backend.
