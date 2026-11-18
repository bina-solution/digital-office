---
title: Turn an app on and off
description: Turn an app on from the «Apps» screen or from the terminal, and turn it off without losing data.
---

## Why

The office runs only the apps that are on in it. Turn an app on when you need it, and off when you do not. Turning it off keeps the data.

## Before you start

- You signed in to the office as the owner. The «Apps» screen is for administrators only.
- The app's id. They are all on [the apps page](/en/apps).

## From the screen

1. Open «Apps» in the centre.
2. Find the app and turn it on.

   The screen goes all the way: it writes the decision, prepares the app, brings it up, waits for it to be healthy, and connects it to the sign-in.

![The «Apps» screen with an app being turned on](TODO-shot: app-management, after clicking to turn on «Files», demo office, desktop 1440x900, light theme)

## From the terminal

1. Record the decision:

   ```bash
   ./bbox apps enable <app>
   ```

   You can give several apps in one command.

2. Bring the office up so the decision runs:

   ```bash
   ./bbox run
   ```

   Without this step nothing comes up. `bbox apps enable` only writes the decision, and says so.

## Before turning it on: is there room?

```bash
./bbox app-management room <app>
```

The command says whether the computer has the processor and memory for the app.

## To turn it off

```bash
./bbox apps disable <app>
./bbox run
```

The app's data is kept. When you turn it on again, it is there.

If another app that is on needs it, the app keeps running even after you turn it off.

## Apps that are not turned off

The base apps (`platform-base/`) are not turned off from the screen.

## How to check it worked

```bash
./bbox app-management apps
```

The command shows every app, what was decided for it and what actually runs. An app you turned on also appears as a tile in the centre.

## See also

- [The apps](/en/apps)
- [The command line](/en/reference/cli)
