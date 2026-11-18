---
title: Connection
description: Where a key, a password or a sign-in for an outside service lives — «Connections», the office's one vault — and how an app gets it without holding it.
---

## The problem

Every app needs something from outside: a key for a language model, a password for a mailbox, a sign-in to an account. If every app keeps its own, nobody knows what there is and where, and one app that is broken into exposes everything it holds.

## The idea

### One place for every secret

«Connections» (`connections`) is the office's vault: the one place for every key, password and sign-in for an outside service. Its screen shows each connection, its state, where its value came from, and which apps use it.

### What counts as a connection

Anything an app needs in order to talk to a service. For example:

- A text key, such as a language-model key.
- A password, or a mailbox's app password.
- An OAuth sign-in: a permission you gave a service once.
- A session opened by scanning a QR code, such as WhatsApp.
- A rotating one-time code (TOTP).

### Where the value comes from

The vault looks for a value in a fixed order:

1. What is stored in it.
2. On the first run: a value written in `.env`, so that a new office starts without asking.
3. Only what is still missing, it asks for.

Every connection has a live check. That way the screen shows whether the connection really works, not only whether it has a value.

### An app gets permission, not a secret

The goal: an app does not hold secrets permanently. It asks the vault for access, and gets only the connections its `app.json` declares. A request for a connection that was not declared is refused by name, and every grant is written to a log you can read: who got what, and when.

Where this stands today:
- Five apps (`indox`, `apitools`, `mail`, `my-docs`, `chat`) still hold secrets in their own settings. Their move to the vault continues.
- By default the vault is in warning mode. A requester it does not recognise yet gets an answer, and the request is logged. Enforcement mode, in which an unrecognised requester is refused, is the goal.

### What only you do

Two things the vault cannot do by itself: approve an OAuth permission on the service's screen, and scan a QR code with your phone.

## What this makes possible

- You see in one place everything the office is connected to, and which of them do not work.
- You replace a key in one place, and every app that uses it gets the new one.
- Once the move is complete, an app that is broken into will not hold everyone else's keys.
- A connection to a new service is one entry in the vault's catalogue, with no code.

## Going further

- [The concepts](/en/concepts)
- [App](/en/concepts/app)
- [Office](/en/concepts/office)
