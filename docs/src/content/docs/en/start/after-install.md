---
title: After the install
description: Find the office's address, sign in first, check that everything is healthy, and keep the .env file safe.
---

## Why

The office is up. Now you need to find it, sign in to it before anyone else, and keep the settings file safe.

## Before you start

`./bbox run` has finished (on Windows `bbox.cmd run`).

## The steps

1. **Find the address.** The office's addresses are the `*_BASE_URL` values in the `.env` file. The centre is `CONSOLE_BASE_URL`.
   - On macOS: `http://console.localhost:8080`.
   - A local office on Linux (no domain, `DGO_LOCAL=1`): `http://console.localhost`.
   - An office with a domain, on Linux or Windows: the value of `CONSOLE_BASE_URL` in `.env`, derived from the business name: `console.<slug>.digital-office.co.il`.

   > TODO-product: a Windows office without a domain. It is not measured yet whether `bbox.cmd install windows` leaves the office local, like `DGO_LOCAL=1` on Linux.

2. **Sign in first.** A new office comes with no users. On the first run `./bbox run` prints a one-time link:

   ```
   [forward-auth] first run: open <sign-in address>/setup?code=<code>&rd=<centre address>
   ```

   Open the link, write a name and a password of at least 12 characters, and you are the office's first administrator, signed in.
   The link works until the administrator is created, and never after. Do not send it to anyone: whoever opens it first is the administrator.

   ![The card that creates a new office's first administrator](TODO-shot: the /setup card on a new demo office; desktop 1440x900, light theme; and on a phone 390x844)

3. **Check the office.** The first shows the state of the containers, and the second checks the office and exits without an error when everything is healthy:

   ```bash
   ./bbox status
   ./bbox verify
   ```

   On a new office, do not run `./bbox onboarding`: it waits about four minutes for n8n, which is off on a new office, and ends with «n8n REST not ready yet».

   To only check the permissions again and get fresh sign-in links:

   ```bash
   ./bbox onboarding --auth-state
   ```

4. **Keep `.env` safe.** It holds all the office's secrets, and it does not go into `git`. Do not keep secrets in other files in the repository.

## How to check it worked

- You signed in to the centre and saw the tiles.
- `./bbox status` shows the containers healthy.
- `./bbox verify` exits without an error.

## Cleaning up

`./bbox stop` takes the office down and keeps the data.
`./bbox reset` **deletes all the data**, and asks first.

## What next

- [The first hour](/en/start/first-hour)
- [The concepts](/en/concepts)
