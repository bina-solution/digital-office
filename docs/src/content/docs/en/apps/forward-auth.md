---
title: Identity and sign-in
description: "The office's sign-in service (forward-auth): the first sign-in, inviting a person, signing out of every app — and its limits, written once."
---

## What it is

«Identity and sign-in» (`forward-auth`) is the office's identity service: one executable that stands in front of every app. Whoever has not signed in reaches the sign-in form. Whoever has signed in passes to the app, and the app knows who they are. The service is part of the base of every office (layer 1), and it replaces authentik: new offices have signed in through it since 2 November 2026.
How to use it: [Sign-in and users](/en/use/sign-in).

## The first sign-in

A new office has no user yet. The first run of `./bbox run` prints a one-time link with `/setup`. Whoever opens it first chooses a name and a password of at least 12 characters, and is the owner. After that the link no longer works.

## Inviting a person

| Command | What it does |
|---|---|
| `./bbox forward-auth invite <user> <email> [display]` | Returns a one-time link for the person, good for seven days |
| `./bbox forward-auth invite --list` | The invitations still open, without the codes |
| `./bbox forward-auth invite --revoke <user>` | Cancels an invitation |

The person opens the link, sees their name, and chooses a password of at least 12 characters themselves. Nobody else knows it.

## Signing out

Signing out clears the sign-in in this browser, and cancels every earlier sign-in of the same person in every app.

## There is no screen for managing users

The address `/whoami` returns who signed in. That is all the service shows. It has no screen for managing users, and a person is added only by invitation.

## The limits, once

- **One address for everyone.** The limit on attempts is per address. When every client arrives from the same address (like port 8080 on a Mac or on a phone), it is one limit for everyone, and a stranger on the same network can block it for a while.
- **Codes in the log.** The edge router's access log records addresses, so one-time codes appear in it until they are used. Whoever reads that log has full rights over the office anyway.
- **Sign-out is kept in memory.** Restarting the service forgets it, and sign-ins that were cancelled come back until they expire. Replacing the service's secret ends every sign-in for good.
- **A service inside the office's network** can reach the sign-in service directly, without passing through the edge router, and present itself from any address it likes. That way it gets around the per-address limit on attempts.

## How to check it works

- An app's address, without a sign-in, leads to the sign-in form.
- After signing in, `/whoami` returns your name.

## Going further

- [Sign-in and users](/en/use/sign-in)
- [After the install](/en/start/after-install)
- [Connections](/en/apps/connections)
