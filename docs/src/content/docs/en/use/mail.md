---
title: Mail
description: Connect a mailbox, read and find mail, and mark it, from the «Mail» screen or from the terminal.
---

## Why

«Mail» (`mail`) holds all the office's mailboxes in one place: Gmail mailboxes, and the addresses of the office's own mail server. Each mailbox is a **connection**.

## Before you start

- «Mail» is on. On a new install it is on. If not: [Turn an app on](/en/use/add-app).
- For Gmail: an app password of your Google account.

## Connect a mailbox

1. Open the «Mail» tile in the centre.
2. Choose «Connect account».
3. Connect Gmail with an app password.

![«Mail» with the «Connect account» window open](TODO-shot: mail, «Connect account» open, demo office, desktop 1440x900, light theme)

All the mailboxes appear in the «Accounts» menu. The mailbox you chose in one window changes nothing in another window.

## Read and find from the terminal

1. **The mailboxes, and the default:**

   ```bash
   ./bbox mail profile list
   ```

   The mailbox marked with `*` is the default.

2. **The newest mail in a mailbox:**

   ```bash
   ./bbox mail -p <mailbox> inbox 5
   ```

   Without a number: ten.

3. **Search:**

   ```bash
   ./bbox mail -p <mailbox> find "from:bank" 5
   ```

   The search is written in Gmail's search language.

4. **One message:**

   ```bash
   ./bbox mail -p <mailbox> read <id>
   ```

`-p` chooses a mailbox by its address, name or id.

## Mark and label

```bash
./bbox mail -p <mailbox> mark <id> starred
./bbox mail -p <mailbox> tag <id> +<label>
```

Marking and labelling change the mailbox itself, in Gmail too. A command that writes does not run without `-p`, so that it does not write to a mailbox you did not choose.

Sending is done from the screen only.

## Mail from the internet to the office's addresses

By default, `MAIL_BIND=127.0.0.1` in `.env`. That way **no mail from the internet reaches** the office's addresses. An office with a public address needs `MAIL_BIND=0.0.0.0`.

The addresses' domain is `MAIL_DOMAIN` in `.env`.

## How to check it worked

```bash
./bbox mail profile list
./bbox mail -p <mailbox> inbox 1
```

What you will see: the mailbox you connected, and the latest message in it.

## See also

- [Files](/en/use/files)
- [Ask Bina](/en/use/ask-bina)
