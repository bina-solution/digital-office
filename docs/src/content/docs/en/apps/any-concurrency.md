---
title: Any Concurrency
description: "The timeline of everything that runs in the office at once — n8n flows, requests at the edge router, containers and apps' events — to answer «what was running when it got slow»."
---

## What it is

«Any Concurrency» (`any-concurrency`) draws on one timeline everything that runs in the office at the same time: [Automations](/en/apps/n8n) flows, requests through the [edge router](/en/apps/traefik), containers that went up and down, and events apps send. Each row is a time bar. It answers questions like «what was running when it got slow», «did the two flows overlap», and «is the queue filling up».

It is for administrators only, off in a new install, and is in the «Any Concurrency» tile in the «Infrastructure» group. [Raphael](/en/apps/raphael) reads from it.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings it up:

```bash
./bbox apps enable any-concurrency
./bbox run
```

## It only reads

Its sources: n8n's database (read only), its queue and its event log, the edge router's log, the container engine's events, logs that apps declare, time bars that apps serve (for example «INDOX», Plane, «Bina» and «Security»), bars sent to it, and every app's [event stream](/en/apps/redis). It does not stop, start or delete anything. To act on what you see, go to the app responsible for it.

## From the command line

| Command | What it does |
|---|---|
| `./bbox any-concurrency sources` | Every source: on, answering, and the latest event |
| `./bbox any-concurrency queue` | n8n's queue now |
| `./bbox any-concurrency executions` | n8n's runs in the time window |
| `./bbox any-concurrency spans` | A window's time bars. You can give hours and sources |
| `./bbox any-concurrency verify` | Fails when the container is not running or when a source that is on does not answer |

`verify` also fails when it cannot read the health state. About log lines it only warns, and exits 0. Read the output, not only the exit code.

## What does not work yet today

- **The bars are kept in memory, not in a database.** On a restart, bars sent to it are lost. The edge router's and the containers' rows come back only in part: the last 2000 lines of the log, and the containers running now. A sparse row after a restart does not mean the office is quiet.
- **It is heavy.** It is the largest consumer of the processor on the computer, and many requests at once for the time bars sometimes get 503.
- **A source that receives events counts as «healthy» when its door is open,** not when events actually arrived.

## Going further

- [Automations](/en/apps/n8n)
- [Raphael](/en/apps/raphael)
- [Cache and queues](/en/apps/redis)
