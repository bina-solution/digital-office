---
title: Cache and queues
description: "The office's Redis: cache, queues, locks and every app's event stream — 256 MB, and what happens when it fills up."
---

## What it is

«Cache and queues» (`redis`) is the office's Redis 7: the apps' cache, queues and locks. It is part of the base of every office (layer 1), and has no tile.

## The event stream

Apps that publish events write them here, each in a stream of its own: a new message, a site that went up, a command that ran on a computer. Each event is one line a person can read.

| Command | What it does |
|---|---|
| `./bbox redis flow` | The last ten events, from every app together, then each new event as it happens |
| `./bbox redis flow <app>` | Only one app's |
| `./bbox <app> flow` | The same, in an app that publishes events (for example `drive`, `meet`, `computers`) |

A stream is a window: it keeps up to about a thousand events, and is deleted after 30 days with no new event.

## The memory

Redis has 256 MB. When they fill up it deletes nothing by itself, and refuses every new write. So everything written here needs an expiry time, except the queues themselves.

## Backup

**Redis is not part of the backup.** It is a cache, and there is nothing in it to bring back. The backup checks this on every export: a key with no expiry time, that is not of a known kind (queue, cache or lock), fails the export. Redis does save a copy to disk from time to time, to come back after a restart.

## Access from the computer

The [edge router](/en/apps/traefik) passes port 6379 to it, and only under conditions: over an encrypted connection, by the name `REDIS_HOST`, and from addresses in the `DBS_ALLOWED_IPS` list. The port is bound to the local address only. The password does not appear on the command line of the container or of its health check.

## What does not work yet today

- **The memory limit is not yet below the container's limit.** Both are 256 MB. Saving to disk copies the memory, and a full Redis can get stuck in such a save. The limit will come down once every office has been measured.

## Going further

- [Edge router](/en/apps/traefik)
- [Backup](/en/backup)
- [Database](/en/apps/postgres)
