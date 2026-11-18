---
title: Chat
description: "The office's conversations in one place: internal chat, WhatsApp and Telegram, each as an account. What reaches real people, and what is not locked yet."
---

## What it is

«Chat» (`chat`) brings the office's conversations together in one place: chat between the people in the office, WhatsApp and Telegram. It is off in a new install, and is in the «Chat» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable chat
./bbox run
```

## Accounts

Every channel is an account, and is kept as a [connection](/en/concepts/connection):

| Channel | What it is |
|---|---|
| Local | The chat between the people in the office |
| WhatsApp | One phone linked to the office, like a WhatsApp linked device |
| Telegram | A bot |

A bot can be connected to every account, and it answers what comes in by itself (not on Telegram, see below).

**One phone, one client.** A second WhatsApp client started on the same phone disconnects it from WhatsApp. Link the phone, or link it again, only from [Connections](/en/apps/connections) in the centre.

## What reaches real people

Every send on WhatsApp or Telegram goes out from the business's number or bot, to real people: a message, a file, a message to several conversations, creating a WhatsApp group, and adding or removing people from a group. Connecting or disconnecting a bot changes what people receive.

## From the command line

The operator has one command: `./bbox chat drop-legacy-chat`. (The `prepare` command runs by itself during `./bbox run`.) `drop-legacy-chat` deletes seven old tables. Without `--apply` it only shows what it will do. With `--apply` it keeps a copy and deletes. That is the owner's decision.

## What does not work yet today

- **Anyone inside the office's network can send.** The default is `CHAT_CALLER_MODE=warn`: a request from someone the app does not recognise is answered and written to the log, not blocked. That is, any service on the office's network can send on WhatsApp in the owner's name. `CHAT_CALLER_MODE=enforce` blocks, but then whoever calls without a token is blocked too, like the office's agent and an n8n flow that has no credentials. The fault is being handled.
- **A bot connected to Telegram answers nobody.** Incoming messages from Telegram are shown on the screen, up to about 24 hours back, but there is no permanent listener, so a bot does not answer them.
- **Documents sent on WhatsApp do not reach [INDOX](/en/apps/indox).** According to the code (this was not measured on a live office), the app sends them to an address «INDOX» does not have, and its two fallback flows in n8n are not set up anywhere.
- **A request without an account** acts on the account last chosen on the screen, or on the first administrator's account. That can be the owner's WhatsApp. Whoever writes to this app from code should name an account in every request.
- **The app's README** still describes the bot it grew out of, not what it is today.

## Going further

- [Connections](/en/apps/connections)
- [INDOX](/en/apps/indox)
- [Notifications](/en/apps/notifications)
