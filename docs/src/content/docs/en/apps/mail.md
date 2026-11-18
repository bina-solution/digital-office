---
title: Mail
description: "Every mailbox of the office behind one interface: Gmail and the office's own mail server — how to connect a mailbox, what changes the mailbox itself, and the commands."
---

## What it is

«Mail» (`mail`) holds every mailbox of the office behind one interface: Gmail mailboxes, and the addresses of the office's own mail server. Each mailbox is a [connection](/en/concepts/connection). It is on in every new office. In the centre it is the «Mail» tile in the «Business» group, and on a phone it has a place in the bottom bar.
How to use it day to day: [Mail](/en/use/mail).

## Connect a mailbox

On the screen, «Connect account» connects Gmail in one of two ways:

- **An app password** of a Google account. This way works today.
- **Sign in with Google.** This way does not work today on any office.

The «Accounts» menu shows every mailbox. Each window shows the mailbox chosen in it, and switching to another mailbox changes nothing on the server.

## What changes the mailbox itself

- Labelling and marking change the mailbox itself, in Gmail too.
- A command that writes does not run without `-p`, which says which mailbox to write to.
- Sending mail is done from the screen. The command line does not send.
- Automatic labelling of every mailbox, every 15 minutes, runs as an automation in n8n. In a new office n8n is off, so this labelling is off too until it is turned on.

## From the command line

| Command | What it does |
|---|---|
| `./bbox mail inbox [N]` | The newest messages in the mailbox, a line per message (default: 10) |
| `./bbox mail find "<query>" [N]` | Search, in Gmail's search language |
| `./bbox mail read <id>` | One message: the headers, then the text |
| `./bbox mail connections` | The mailboxes, and which of them is chosen |
| `./bbox mail profile list` | The same information, as a table |

The flag `-p <mailbox>` chooses a mailbox.

## How to check it works

- The «Mail» tile opens, and the mailboxes appear in the «Accounts» menu.
- `./bbox mail inbox 5` shows the last five messages.

## Going further

- [Mail: how to use it](/en/use/mail)
- [Connection](/en/concepts/connection)
- [Connections](/en/apps/connections)
