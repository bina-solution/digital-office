---
title: The office's browser
description: "The office's one shared Chromium: signed in to the sites the owner signed in to once, and shown live on screen — what it does in the owner's name, and what is not locked yet."
---

## What it is

«The office's browser» (`browser42`) is the office's one shared Chromium: one profile and one set of cookies, signed in to the sites the owner signed in to once. It is used for a site that has no API, to read a page the way a person sees it, and to hand a person a screen: a QR code or a sign-in. The owner sees the same browser live in the tile, so every tab opened in it is in front of their eyes.

It is for administrators only, off in a new install, and is in the «The office's browser» tile in the «Business» group. [Social networks](/en/apps/social-list) uses it on a network that has no API.

**It is heavy:** six containers, with limits of about 3.7 GB together. On a computer with little memory, think before you turn it on.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings it up:

```bash
./bbox apps enable browser42
./bbox run
```

## It acts in the owner's name

- **A click on a signed-in site is the owner's click.** Read freely. Whatever sends, buys, deletes or submits on a site needs their approval, in their own words.
- **Nobody types a password.** A person signs in to the site, on the live screen, or the browser fills the password in by itself from its own password store. The only automatic sign-in is to Facebook, and it takes the credentials from the vault without them appearing anywhere.
- **Handing over to a person:** when an app needs a person, for example to scan a QR code, the office brings the browser to whoever is watching, and waits until the page says they have finished.

## From the command line

| Command | What it does |
|---|---|
| `./bbox b42 page <url>` | Opens a page, returns its text, and closes |
| `./bbox b42 shot <url>` | Opens a page, captures it, and closes |
| `./bbox b42 tab list` | The open tabs |
| `./bbox b42 logins sessions` | Which sites the browser is signed in to |
| `./bbox b42 sleep status` | The browser sleeps when there is no work. `wake` wakes it |

## What only the owner does

- **Deleting every sign-in** (`state reset --yes`), saving or replacing the profile (`state dump|load`, which stop the browser).
- **Writing to the browser's password store or to the vault.** When the browser holds the store, this also restarts it.

## What does not work yet today

- **The tasks door answers even without a token.** It has a token check, but the default is «warn» (`BROWSER42_TASK_AUTH=warn`): whoever calls without a token is served, and written to the log. The office's containers reach it, and the offices this app was given to. `refuse` answers 401.
- **Heavy on memory.** On a computer with little memory the browser can hold hundreds of processes.
- **The browser shares a network with every app.** What keeps them from reaching its internal interfaces directly (control of the browser, the live view) is only the start script, which binds them to the local address. The fault is open.

## Going further

- [Social networks](/en/apps/social-list)
- [Identity](/en/apps/digital-assets)
- [Connections](/en/apps/connections)
