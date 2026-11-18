---
title: Connections
description: "The office's vault: what its screen shows, where each value comes from, how it checks that a connection works — and what does not go through it yet."
---

## What it is

«Connections» (`connections`) is the office's vault: the one place for every key, password and sign-in for an outside service. It is part of the base of every office (layer 1). The concept itself is explained on the page [Connection](/en/concepts/connection).

## The screen

In the centre, the «Connections» tile in the «Settings» group. The screen is for administrators only.
Every connection appears in its group. Next to each connection you see:

- its state, from a live check;
- where its value came from;
- which apps use it;
- how it is implemented today.

## Where each value comes from

1. What is stored in the vault.
2. On the first run: a value written in `.env`, so that a new office starts without asking.
3. Only what is still missing, the vault asks for.

Two steps only a person can take: approve an OAuth permission on the service's screen, and scan a QR code with a phone (for example for WhatsApp).

## An app that asks for access

An app asks the vault for access, and gets only the connections its `app.json` declares. Every grant is written to a log you can read.

**What does not go through it yet:**

- Five apps (`indox`, `apitools`, `mail`, `my-docs`, `chat`) still hold secrets in their own settings.
- By default the vault is in warning mode: a requester it does not recognise yet gets an answer, and the request is logged.

## From the command line

```bash
./bbox connections flow
```

The command shows the connections' events: added, changed, checked, disconnected. It never shows a secret.

## How to check it works

- The tile opens, and every connection shows a state.
- `./bbox connections flow` shows the latest events.

## Going further

- [Connection](/en/concepts/connection)
- [App Management](/en/apps/app-management)
- [Office](/en/concepts/office)
