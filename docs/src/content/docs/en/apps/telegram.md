---
title: Telegram
description: "The owner's Telegram inside the office: their account, the chats the office listens to, and the message stream for agents — what it opens, and what does not work yet."
---

## What it is

«Telegram» (`telegram`) connects the owner's Telegram account to the office: their own account, not a bot. The office listens only to chats a person turned on, and every new message in them goes into the office's [event stream](/en/apps/redis). Agents and flows get the messages from the stream. It is for administrators only, off in a new install, and is in the «Telegram» tile in the «Main» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable telegram
./bbox run
```

## Connect the account

**Connecting the account is the owner's action, on the «Telegram» screen:** a QR code, or a phone number and a code. An agent does not sign in in their name, does not ask them for a code, and does not touch the session string.

## A chat you turn on

- **Turning a chat on opens it to every agent of the office,** its history included. Turn a private chat on only when the owner asks.
- **On the first connection** the office turns on by itself the group whose name is written in `TELEGRAM_WATCH_DEFAULT`, if the account is a member of it.
- **Sending from the office is written in the owner's name,** and only to a chat that was turned on.
- **A bot token** goes from BotFather straight to the office's vault. A token pasted in a chat that was turned on is hidden before it reaches the stream.

## From the command line

| Command | What it does |
|---|---|
| `./bbox telegram status` | Whether connected, in whose name, which chats, and whether the stream is written |
| `./bbox telegram flow` | The last ten events, then every new event |
| `./bbox telegram chats` | The account's chats, and for each whether it is on |
| `./bbox telegram history <chat_id>` | The latest messages in a chat that is on, oldest to newest. Tokens are hidden |
| `./bbox telegram media-save <chat_id> <message_id>` | Saves a message's file in [Files](/en/apps/drive), of any size. On the screen this is «Save to Files» |

## What does not work yet today

- **A file over 20 MiB** is not read in place. Save it first in «Files» (`media-save`), and read it from there.
- **One account, one process.** Do not turn on «Telegram TV» with the same account in the same office.
- **«Healthy» does not say Telegram works.** `./bbox telegram status` says whether the account is really connected, and if not, why.

## Going further

- [Cache and queues](/en/apps/redis): the event stream
- [Chat](/en/apps/chat)
- [Connections](/en/apps/connections)
