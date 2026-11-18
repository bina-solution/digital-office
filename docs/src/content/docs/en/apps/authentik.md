---
title: Authentik
description: "The office's previous sign-in service. A new office signs in through «Identity and sign-in»; Authentik stays for offices installed before it, until they move."
---

## What it is

Authentik (`authentik`) is the identity service of offices installed before 0.3.0: users, one sign-in for every app, and sign-in through Google. It runs in four containers: the server, a background worker, a guard that applies its configuration (bootstrap), and a database of its own.

**A new office does not use it.** Since version 0.3.0, [Identity and sign-in](/en/apps/forward-auth) (`forward-auth`) replaces it, and it is off in the default file.

## Which service the office asks

The `DGO_IDENTITY` line in `.env` tells the edge router whom to ask:

| Value | Who |
|---|---|
| `forward-auth` | A new office |
| `authentik` | An office installed before 0.3.0, until it moves |

**If the line is missing from `.env`, the router asks Authentik.** The office's state file (`platform.state.yaml`) must turn on the same service the line chooses.

## Going further

- [Identity and sign-in](/en/apps/forward-auth)
- [Sign-in and users](/en/use/sign-in)
- [Edge router](/en/apps/traefik)
