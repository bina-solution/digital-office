---
title: Raphael
description: "The guardian agent: n8n flows that scan the office on a schedule and report what is out of line. They scan and report, and change nothing — and what does not reach the agent yet."
---

## What it is

«Raphael» (`raphael`) is the hands of the guardian agent: [Automations](/en/apps/n8n) flows that scan the office on a schedule, and when they find something out of line, write a message in [Notifications](/en/apps/notifications). It has no container. The agent Raphael itself, with its skills, is a definition inside [«Bina»](/en/apps/bina-ds).

It is off in a new install. Turning it on also starts n8n.

```bash
./bbox apps enable raphael
./bbox run
./bbox raphael start
```

`./bbox run` already brings the flows up. `./bbox raphael start` makes sure they are in n8n, and from then on they run by themselves. It needs n8n running, and a valid `N8N_API_KEY` key in `.env`. If there is none, it creates one with `N8N_OWNER_EMAIL` and `N8N_OWNER_PASSWORD`.

## What it scans, and when

| Scan | How often |
|---|---|
| Heartbeat | 5 minutes |
| The machine and the containers | 15 minutes |
| The collector («Any Concurrency»): that its sources answer and have not gone quiet | 15 minutes |
| The data | 6 hours |
| The computers' security audit (read only) | Once a week |

Two scans need another app: the collector check needs `any-concurrency`, and the computers audit needs [Computers](/en/apps/computers). Both are off in a new install. Without them, the collector check reports «the collector does not answer», and the audit reports that it could not run.

**The flows scan and report. They never change the system.** A fix is a suggestion Raphael makes to the owner.

## What does not work yet today

- **A finding does not wake an agent.** The flows have no credentials on purpose, so they cannot open a conversation with the agent. What arrives is the message in Notifications.
- **The wake-up message is not read.** Three of the scans (the heartbeat, the collector and the audit) write a message meant to wake the office's agent, but the part that read it was deleted. The message looks delivered, and nobody reads it.

## Going further

- [Automations](/en/apps/n8n)
- [Notifications](/en/apps/notifications)
- [«Bina»](/en/apps/bina-ds)
