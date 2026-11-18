---
title: Error tracking
description: "GlitchTip in the office: apps send it their errors, and «Notifications» turns them into messages — how to turn it on, and what it does not do."
---

## What it is

«Error tracking» (`glitchtip`) is GlitchTip, an error-tracking service compatible with Sentry. Apps send it their errors. [Notifications](/en/apps/notifications) checks every minute for the errors not resolved yet, and turns them into messages. It is for administrators only, and is in the «GlitchTip» tile in the «Infrastructure» group.

In a new install it is off. Turn it on from the command line: `apps enable` only writes the decision, and `./bbox run` brings it up and sets it up:

```bash
./bbox apps enable glitchtip
./bbox run
```

## How an app reports

Every app that defines error tracking gets a project of its own, and a reporting address (DSN) written to `.env`. The setup happens by itself on every `./bbox run`: an organisation, projects, reporting addresses, and a read-only key for «Notifications».

The reporting addresses are internal to the office. An app reports without passing through the edge router, and an error sent to the server from outside is not taken in.

An error marked as resolved in GlitchTip marks its message as read by itself.

## From the command line

| Command | What it does |
|---|---|
| `./bbox glitchtip verify` | Checks that the setup is complete: the «Notifications» key is in `.env` |

## Worth knowing

- **The screen is behind the office's sign-in,** and its self-registration is off.
- **The administrator's password is set in `.env`.** Every `./bbox run` sets it back from there, so change it there, not on GlitchTip's screen.
- **Replacing GlitchTip's secret replaces every reporting address,** and every app needs a restart.

## What does not work yet today

- **The apps screen does not turn it on.** An app of the base is turned on today only by command or on the first install.
- **GlitchTip does not send mail.** The default only writes it to the log. The messages arrive through «Notifications».
- **An office whose `.env` still says `GLITCHTIP_ENABLE_REGISTRATION=true`** leaves registration open behind the sign-in, until the line changes.

## Going further

- [Notifications](/en/apps/notifications)
- [Security](/en/apps/security)
- [The apps](/en/apps)
