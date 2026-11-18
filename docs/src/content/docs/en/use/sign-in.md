---
title: Sign-in and users
description: How the office's owner is created, and how to invite another person.
---

## Why

Every app in the office is behind one sign-in. In a new office, the sign-in service is `forward-auth` («Identity and sign-in»). The owner is created once, and then invites people.

## Before you start

- A new office brought up with `./bbox run`.
- Access to the terminal of the computer that runs the office.

## The steps

1. **Find the first-run link.** On the first run, `bbox run` writes a line in the terminal that starts with `[forward-auth] first run: open`. After it comes a link to the `/setup` page with a one-time code.

   The link works until an owner is created, and never after.

2. **Create the owner.** Open the link in a browser. Choose a name and a password of at least 12 characters. The browser signs in, and arrives at the centre.

   ![The first-run card: name and password](TODO-shot: forward-auth /setup with a valid code, demo office, desktop 1440x900 and phone 390x844, light theme)

3. **Invite another person.** From the terminal:

   ```bash
   ./bbox forward-auth invite <user> <email> [display]
   ```

   The command prints a one-time link. Send it to the person yourself. The link is valid for 7 days. A new invitation for the same person replaces the previous link.

4. **The person chooses a password.** They open the link, see a card with their name and two password fields (at least 12 characters), and sign in.

   ![The invitation card with the person's name and the password fields](TODO-shot: forward-auth /invite with a valid code, demo office, phone 390x844, light theme)

## What an invited person sees

An invited person opens the office's apps, except administrators-only apps. An app marks that in its `app.json` (`people: admins`). The list of those apps is on [the apps page](/en/apps).

## Managing invitations

The invitations not used yet:

```bash
./bbox forward-auth invite --list
```

To cancel an invitation:

```bash
./bbox forward-auth invite --revoke <user>
```

## How to check it worked

- You signed in to the centre with the name and password you chose.
- `./bbox forward-auth invite --list` no longer shows whoever signed in.

## When something does not work

- **The link says it is not valid.** The invitation expired, was used, or was replaced. Create a new invitation.
- **Many wrong sign-in attempts.** After five mistakes, the address is blocked for 60 seconds, and the time doubles up to an hour.
- **No `first run` line in the terminal.** The office already has an owner.

## See also

- [After the install](/en/start/after-install)
- [Identity and sign-in](/en/apps/forward-auth): the service behind the sign-in, and its limits
- [The apps](/en/apps)
