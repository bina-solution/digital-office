---
title: Automations
description: "n8n, the office's automation engine: why it runs even when it is off, where the flows are written, how to update a flow safely, and what is open to the world."
---

## What it is

«Automations» (`n8n`) is the office's flow engine. Every flow of every app runs in it: for example the sync of [INDOX](/en/apps/indox) and the transcription of [Video meetings](/en/apps/meet). It is for administrators only, and is in the «n8n» tile in the «Infrastructure» group.

**It runs even when it is off.** In the default file it is off, but «Bina», «INDOX», «Files» and «Mail», which are on in a new install, need a flow engine, so the office starts it for them. «Video meetings», «Chat» and «Raphael» need it too when they are turned on. Turning it off does not stop it as long as one of them is on.

## What it is made of

The editor and the API, a service that receives webhooks, two workers, and a database of its own. Work passes through a queue, and the workers pull from it.

## The flows are written in code

Every app brings its flows as `*.workflow.ts` files in its folder. **The code is the source.** What runs in n8n is a copy built from it.

| Command | What it does |
|---|---|
| `./bbox n8n status` | The flows, the activity and the health |
| `./bbox n8n pull <app> <wfId>` | Copies one flow from n8n to the code. Do this first |
| `./bbox n8n push <app> <wfId> --dry-run` | What an update would change |
| `./bbox n8n push <app> <wfId>` | Updates n8n from the code, restarts the flow and reads it back. n8n itself is not restarted |
| `./bbox n8n plan <app> <wfId>` | How to test the flow |
| `./bbox n8n test <app> <wfId>` | Runs the flow for real, with all its effects |
| `./bbox n8n exec list` | The runs, for diagnosis |

## How to update a flow safely

1. Pull exactly the flow you are editing: `pull <app> <wfId>`.
2. Edit the code.
3. `push … --dry-run`, then `push` of that flow only.

**`pull <app>` without an id** rewrites from n8n every file of the app that has no unpushed edits, deletes the comments from them, and deletes the file of a new flow not pushed yet. Do not do it.

**A conflict on update** says someone changed the flow directly in n8n. First check what changed. `--force` overwrites that change.

**`test` runs for real.** Run `plan` first.

## What is open to the world

The editor stands behind the office's sign-in, and behind n8n's own account. Only three paths are open to the whole world, with no sign-in: `/webhook/`, `/webhook-waiting/` and `/form/`. Whoever calls them is another machine, with no sign-in, so every flow that receives a webhook must check for itself who is calling.

## What only the owner does

- `push all` and `pull all`: they act on every flow, and `push all` also restarts n8n and the workers.
- `./bbox n8n <app> unpush`, which deletes every flow of the app without asking, and restarts n8n.
- Every action that deletes or resets n8n's database.

## What does not work yet today

- **The local n8n always starts.** An app's flows can run in the n8n of another office in the herd. But even when the herd's plan (`herd.yaml`) places n8n in another office, this office chooses only from what it has and starts its own n8n. An explicit off does not stop it either.
- **On a server without node, a new flow that should be active is created off.** The update checks whether to activate a new flow with the server's own `node`. Without `node` the answer is «no».
- **A new flow with a schedule** starts running on its schedule only after n8n is restarted.

## Going further

- [INDOX](/en/apps/indox)
- [Video meetings](/en/apps/meet)
- [Herd](/en/concepts/herd)
