---
title: Bina
description: "The office's agents app: who lives in it, what costs money and what is free, what only the owner decides, and how it updates without stopping work."
---

## What it is

«Bina» (`bina-ds`) is the office's agents app: a Hebrew harness where the office's agents live. It is on in every new office. In the centre it is the «Azaria» tile in the «Main» group, for administrators only.

- **«Azaria»** is the default agent, and it acts.
- **«Raphael»** is the guard, and it only suggests.

People talk to them in the tile. Every other caller (a script, another agent, a linked office) talks to the agent through one interface, `agent.v1`, and from the terminal that is `./bbox agent`. How the agent learns the apps: [Agent](/en/concepts/agent).

## What costs money and what is free

- **A conversation costs money, and acts.** A new message, a task or a goal starts the language model, and the agent works with full access to the office. A message to the agent is an instruction to an operator with full rights, so give it only what you really asked for.
- **Reading conversations is free.** Cancelling stops the queue that is running now.
- The model itself is a [connection](/en/concepts/connection): a key kept in «Connections».

## What only the owner decides

- Changing the model also changes the office's default model.
- Changing the preset changes how a conversation behaves.

## Updating without stopping work

«Bina» is not rebuilt from a conversation running inside it. When a command would rebuild it from inside, the office hands the work to a helper that runs outside it. The helper waits for quiet, forces the update after three hours, and goes back to the previous version if the new one is not healthy.

## From the command line

| Command | What it does |
|---|---|
| `./bbox agent list` | The conversations: running or waiting, title and goal |
| `./bbox agent show <id>` | One conversation. Reading, free |
| `./bbox agent wait <id>` | Waits for the conversation to finish |
| `./bbox agent cancel <id>` | Stops the running queue |
| `./bbox agent new <text>` | A new conversation. Costs money |

In an office where «Bina» is off, `./bbox agent --office <office>` reaches the agent of a linked office.

## How to check it works

- The «Azaria» tile opens and shows the conversations.
- `./bbox agent list` returns the list of conversations.

## Going further

- [Agent](/en/concepts/agent)
- [Ask Bina](/en/use/ask-bina)
- [Connections](/en/apps/connections)
