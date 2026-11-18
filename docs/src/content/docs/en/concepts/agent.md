---
title: Agent
description: What the office's agent, «Bina», is — how it learns every app, how you talk to it, where its tasks are, and why you check what it did and not what it said.
---

## The problem

An AI agent that only answers does not do the work. And an agent that does it needs to know how every app in the office works, to get tasks, and to leave behind something that can be checked.

## The idea

### One agent, one interface

The office's agent, «Azaria», lives in the «Bina» app (`bina-ds`). The office talks to it through one interface, `agent.v1`. «Bina» is the first implementation of that interface: a harness that runs a language model. Another agent can replace it if it answers the same interface, and no app will need to change.

### How it learns every app

Every app has a brief, `AGENT.md`, in its folder. The compiler gathers the briefs of the apps that are on into one file, and the agent reads it in every conversation. When an app is turned off, its brief leaves the file.
It acts in the apps the same ways a person does: [the command line and the API](/en/concepts/app).

### How to talk to it

- **In the centre:** the «Azaria» tile. There you see every conversation, and there you answer when the agent asks a question.
- **From the terminal:** the command `./bbox agent`, with the same actions the screen has. For example `./bbox agent list` shows the conversations, and `./bbox agent wait <id>` waits for a conversation to finish.

A running conversation is not a fault. A new message joins the queue after what the agent is doing now, or goes into it and changes its direction.

### Its tasks

The agent's tasks are items in the office's project tool. It has an account of its own there, and the items are assigned to it. `./bbox agent do <REF>` gives it an item: it opens a conversation named after the item and works on it.

### Check what it did

The agent's answer is text. What it did, you check in the system itself: in the file, in the app, in the item. Do not rely on what the answer says.

## What this makes possible

- The agent works in every app that is on, without anyone teaching it each one again.
- A task for the agent looks like a task for a person: an item, an assignee, and comments.
- You can replace the model or the harness without changing the office.

## Going further

- [Ask Bina](/en/use/ask-bina)
- [App](/en/concepts/app)
- [The concepts](/en/concepts)
