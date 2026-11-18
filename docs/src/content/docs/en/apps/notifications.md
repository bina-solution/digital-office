---
title: Notifications
description: "The office's message board: errors and events from every app in one list, and what rings on the phone — and when."
---

## What it is

«Notifications» (`notifications`) is the office's message board: errors and events from every app in one list. When something matters, it rings on the phone. It is part of the base of every office (layer 2), and in the centre it is the «Notifications» tile in the «Infrastructure» group.
Other apps write to it. For example, «Self-healing» writes when it restarts a service that fell.

## What rings on the phone

- A phone signs up for notifications from the «Notifications» screen.
- Only a message at the «error» level rings, on every signed-up phone of every person in the office. A message can say whom to ring, and then it rings only for them.
- Messages at the «warning» and «info» levels stay on the board.
- A message that repeats rings again at most once every four hours. Above 30 rings an hour, one summary replaces the rest.

## Managing the board

- Mark what you dealt with as read.
- Deleting and clearing what was read delete messages for good.

## From the command line

The commands only read:

| Command | What it shows |
|---|---|
| `./bbox notifications list` | The latest messages (default: 20). `--unread` shows only what was not read |
| `./bbox notifications show <id>` | One message, in full |
| `./bbox notifications unread` | How many messages were not read |
| `./bbox notifications stats` | How many messages there are, by source and by level |
| `./bbox notifications verify` | Whether the app is healthy |
| `./bbox notifications flow` | The events, the latest and continuing in real time |

## How to check it works

- The «Notifications» tile opens and shows the board.
- `./bbox notifications verify` passes.

## Going further

- [Is the office healthy?](/en/admin/health)
- [Machine](/en/apps/machine)
- [Getting to know the centre](/en/use/console)
